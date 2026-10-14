# Hospital Appointment Booking System

A complete FastAPI backend for booking hospital appointments: role-based login, doctor schedules and leave,
double-booking-safe appointments, a live queue over WebSockets, e-mail notifications, scheduled jobs,
consultations with prescription PDFs, ratings and admin reports.

## 1. Overview and features

| Area | What you get |
|---|---|
| Auth | Register (patients), login, refresh, logout, `/auth/me`; roles `ADMIN`, `DOCTOR`, `PATIENT`; refresh tokens stored (hashed) and revocable |
| Departments / doctors | CRUD, soft delete, filters (department, specialization, name), pagination |
| Schedules / leave | Weekly working hours with breaks, overlap checks, automatic slot generation, leave that cancels affected appointments |
| Appointments | Unique numbers (`APT-20261020-0001`), daily tokens in slot order, 30-day window, 409 on conflicts, DB unique constraints + row locking |
| Lifecycle | `Booked → Checked-In → In Consultation → Completed`, plus `Cancelled` and `No-Show`, with a history table |
| Consultations | Symptoms, diagnosis, medicines, advice, follow-up date; saving completes the appointment |
| Files | PDF / JPG / PNG up to 5 MB, UUID file names, ownership checks (413 / 415 errors) |
| Real time | `WS /ws/queue/{doctor_id}`, `WS /ws/notifications`, `PUT /doctors/me/call-next`, test page at `/queue-test` |
| E-mail + jobs | SMTP via `smtplib` in background tasks, mock mode, APScheduler jobs (reminders, no-shows, follow-ups) |
| Reports | Dashboard, doctor performance, department summary, peak hours, frequent no-shows |
| Bonus | Prescription PDF (ReportLab) and doctor ratings / feedback |

## 2. Technologies

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, MySQL (PyMySQL), Alembic, PyJWT, Passlib + bcrypt,
WebSockets, APScheduler, FastAPI `BackgroundTasks`, `smtplib`, Uvicorn, ReportLab, Pytest, python-dotenv.

## 3. Project structure

```text
hospital_appointment_system/
├── app/
│   ├── main.py              # app, lifespan (scheduler), error handlers
│   ├── config.py            # settings from .env
│   ├── database.py          # engine, session, Base
│   ├── dependencies.py      # get_db, get_current_user, role checks, pagination
│   ├── auth/security.py     # bcrypt + JWT helpers
│   ├── models/              # SQLAlchemy tables
│   ├── schemas/             # Pydantic request/response models
│   ├── routers/             # HTTP layer only
│   ├── services/            # business logic
│   ├── websockets/          # connection manager, events, WS routes
│   ├── jobs/scheduler.py    # APScheduler jobs
│   └── utils/               # clock, exceptions, pagination, db helpers
├── alembic/versions/0001_initial_schema.py
├── scripts/create_admin.py  # optional manual way to create the admin
├── static/queue_test.html
├── uploads/                 # patient files (git-ignored)
├── generated_pdfs/          # prescription PDFs (git-ignored)
├── tests/
├── alembic.ini  .env.example  .gitignore  pytest.ini  requirements.txt  README.md
```

Rule of thumb: **routers** parse HTTP, **services** hold the rules, **models** describe tables, **schemas** validate data.

## 4. Prerequisites

* Python 3.12 (`python --version`)
* MySQL 8.x (or 5.7+) running locally, with a user that can create tables

## 5. Virtual environment (Windows PowerShell)

```powershell
cd hospital_appointment_system
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks the script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 6. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 7. Create the MySQL database

```powershell
mysql -u root -p
```
```sql
CREATE DATABASE hospital_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'hospital_user'@'localhost' IDENTIFIED BY 'your_db_password';
GRANT ALL PRIVILEGES ON hospital_db.* TO 'hospital_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

## 8. Configure `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Important values:

```env
DATABASE_URL=mysql+pymysql://hospital_user:your_db_password@localhost:3306/hospital_db
JWT_SECRET_KEY=<long random string>
MAIL_MODE=mock            # "smtp" to really send e-mail
TIMEZONE=Asia/Kolkata
```

Generate a secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
If your DB password contains `@ : / #`, URL-encode it (`@` → `%40`).
`.env` is git-ignored; never commit it.

## 9. Run the database migrations

The schema is created only by Alembic (the app never calls `create_all()`).

```powershell
alembic upgrade head
```

The first admin account is created **automatically** the first time the server starts (next section),
using `FIRST_ADMIN_*` from `.env`. Nothing extra to run.

Other useful commands: `alembic current`, `alembic downgrade -1`.

## 10. Start the server

```powershell
uvicorn app.main:app --reload
```

On startup the app checks whether the admin from `FIRST_ADMIN_EMAIL` exists. If not, it creates it (role `ADMIN`,
password hashed with bcrypt) and logs `Default admin account created`. On later starts it logs
`Default admin already exists` and changes nothing, so restarting never creates duplicates.
You can then log in at `/docs` with `POST /auth/login` using `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD`.
(The migration must be applied first; otherwise the log says: *Could not create the default admin ... Did you run 'alembic upgrade head'?*)

## 11. Swagger documentation

Open <http://127.0.0.1:8000/docs> (ReDoc: `/redoc`). Click **Authorize** and paste the `access_token` from `/auth/login`.

## 12. Run the tests

Tests use an **in-memory SQLite database**, so your MySQL data is never touched.

```powershell
pytest
pytest tests/test_appointments.py -k double
pytest -x -vv
```

## 13. Authentication and roles

* Access token: 30 minutes. Refresh token: 7 days, stored hashed in `refresh_tokens`, revoked on logout and rotated on every refresh.
* `401` = missing/invalid/expired token. `403` = valid token but not allowed. Inactive users get `403` at login.

| Role | Can do |
|---|---|
| PATIENT | Register themselves, book / reschedule / cancel their own appointments, check in, upload lab reports, see history, download own prescription, rate doctors |
| DOCTOR | Manage own schedule and leave, call next patient, record consultations for own appointments, upload prescriptions/scans |
| ADMIN | Create doctor/admin accounts, manage departments and doctors, manage any schedule, check patients in, reports |

Public registration always creates a PATIENT. The first ADMIN is created automatically at server start from `.env`. More admins and doctors are created by an admin with `POST /auth/users` (role `DOCTOR`), then attach the profile with `POST /doctors`.

## 14. Example workflow (registration → consultation)

```powershell
$base = "http://127.0.0.1:8000"
function Call($method, $path, $body, $token) {
  $h = @{}; if ($token) { $h["Authorization"] = "Bearer $token" }
  Invoke-RestMethod -Method $method -Uri "$base$path" -Headers $h -ContentType "application/json" -Body ($body | ConvertTo-Json -Depth 5)
}

# 1. Admin logs in
$admin = (Call Post "/auth/login" @{email="admin@hospital.org"; password="ChangeMe123"}).access_token

# 2. Admin creates a department, a doctor account and the doctor profile
$dept = Call Post "/departments" @{name="Cardiology"} $admin
$docUser = Call Post "/auth/users" @{email="dr.rao@hospital.org"; password="Doctor1234"; full_name="Dr. Rao"; phone="9876543210"; role="DOCTOR"} $admin
$doc = Call Post "/doctors" @{user_id=$docUser.id; department_id=$dept.id; specialization="Cardiologist"; qualification="MD"; experience_years=10; consultation_fee=500; slot_duration_minutes=30} $admin

# 3. Schedule: Monday (0) 09:00-13:00 with a break 11:00-11:30
Call Post "/doctors/$($doc.id)/schedules" @{day_of_week=0; start_time="09:00:00"; end_time="13:00:00"; break_start="11:00:00"; break_end="11:30:00"} $admin

# 4. A patient registers and logs in
Call Post "/auth/register" @{email="asha@example.com"; password="Patient123"; full_name="Asha"; phone="9000000001"}
$pat = (Call Post "/auth/login" @{email="asha@example.com"; password="Patient123"}).access_token

# 5. Patient looks at free slots and books one (use a real upcoming Monday)
Invoke-RestMethod "$base/doctors/$($doc.id)/available-slots?date=2026-10-19" -Headers @{Authorization="Bearer $pat"}
$apt = Call Post "/appointments" @{doctor_id=$doc.id; appointment_date="2026-10-19"; appointment_time="09:30"; reason="Chest pain"} $pat

# 6. On the day (from 30 min before the slot) the admin checks the patient in
Call Put "/appointments/$($apt.id)/check-in" $null $admin

# 7. The doctor calls the next patient and records the consultation
$dr = (Call Post "/auth/login" @{email="dr.rao@hospital.org"; password="Doctor1234"}).access_token
Call Put "/doctors/me/call-next" $null $dr
Call Post "/appointments/$($apt.id)/consultation" @{symptoms="Chest pain"; diagnosis="Mild angina"; prescription=@(@{medicine="Aspirin"; dosage="75mg daily"; duration="30 days"}); advice="Rest"; follow_up_date="2026-10-26"} $dr

# 8. Patient downloads the prescription and rates the doctor
Invoke-WebRequest "$base/appointments/$($apt.id)/prescription-pdf" -Headers @{Authorization="Bearer $pat"} -OutFile prescription.pdf
Call Post "/appointments/$($apt.id)/rating" @{rating=5; review="Very helpful"} $pat
```

## 15. Sample requests and responses

**Register** `POST /auth/register` → `201`
```json
{"email":"asha@example.com","password":"Patient123","full_name":"Asha","phone":"9000000001"}
```
```json
{"id":2,"email":"asha@example.com","full_name":"Asha","phone":"9000000001","role":"PATIENT","is_active":true,"created_at":"2026-10-12T06:30:00Z"}
```

**Login** `POST /auth/login` → `200`
```json
{"access_token":"eyJ...","refresh_token":"eyJ...","token_type":"bearer","expires_in":1800}
```

**Book** `POST /appointments` → `201`
```json
{"id":1,"appointment_number":"APT-20261019-0001","patient_id":1,"patient_name":"Asha","doctor_id":1,
 "doctor_name":"Dr. Rao","appointment_date":"2026-10-19","appointment_time":"09:30:00","token_number":1,
 "reason":"Chest pain","status":"BOOKED","consultation_fee":500.0,"reschedule_count":0,"created_at":"..."}
```

**Booking conflict** → `409` `{"detail":"This slot is already booked. Please choose another slot"}`

**Validation error** → `422`
```json
{"detail":"Validation error","errors":[{"field":"phone","message":"String should match pattern '^[0-9]{10}$'"}]}
```

**List endpoints** return `{"items":[...],"total":N,"skip":0,"limit":20}` and accept `?skip=&limit=`.

### Endpoint summary

| Group | Endpoints |
|---|---|
| Auth | `POST /auth/register` `/auth/login` `/auth/refresh` `/auth/logout` `/auth/users` (admin), `GET /auth/me` |
| Departments | `POST/GET /departments`, `PUT/DELETE /departments/{id}` |
| Doctors | `POST/GET /doctors`, `GET/PUT/DELETE /doctors/{id}` |
| Schedules | `POST/GET /doctors/{id}/schedules`, `PUT/DELETE /schedules/{id}` |
| Leave / slots | `POST/GET /doctors/{id}/leaves`, `GET /doctors/{id}/available-slots?date=YYYY-MM-DD` |
| Appointments | `POST/GET /appointments`, `GET /appointments/{id}`, `PUT /appointments/{id}/reschedule` `/cancel` `/check-in` |
| Consultation | `POST/GET /appointments/{id}/consultation`, `GET /appointments/{id}/prescription-pdf` |
| Files | `POST/GET /appointments/{id}/files`, `GET /files/{id}/download`, `GET /patients/me/history` |
| Queue | `PUT /doctors/me/call-next`, `WS /ws/queue/{doctor_id}`, `WS /ws/notifications`, `GET /queue-test` |
| Ratings | `POST /appointments/{id}/rating`, `GET /doctors/{id}/ratings` |
| Reports | `GET /reports/dashboard` `/doctor-performance` `/department-summary` `/peak-hours` `/frequent-no-shows` |

Appointment filters: `status`, `doctor_id`, `date_from`, `date_to`, `appointment_number`.

### Business rules in short

* Bookings: future only, up to 30 days ahead; valid slot (working hours, not on a break, not on leave); one appointment per patient per doctor per day; a patient cannot be at two places at the same time.
* Cancel / reschedule: patient owns it, status `BOOKED`, at least 2 hours before the slot; reschedule at most 2 times; the old slot is freed.
* Check-in: on the appointment date from 30 minutes before the slot.
* No-show: a `BOOKED` appointment becomes `NO_SHOW` 15 minutes after its slot (`NO_SHOW_GRACE_MINUTES`).
* Doctor leave: all open appointments in the leave period are cancelled, history recorded, patients e-mailed, queue refreshed.
* Doctor deactivation / deletion is blocked while upcoming open appointments exist.

## 16. WebSocket testing

The access token goes in the query string: `ws://127.0.0.1:8000/ws/queue/1?token=<ACCESS_TOKEN>`.
Invalid or expired tokens are refused (close code 1008). Use an **access** token, not a refresh token.

**Browser test page:** open <http://127.0.0.1:8000/queue-test>, enter the doctor ID and token, press **Connect**.

**Browser console:**
```javascript
const ws = new WebSocket("ws://127.0.0.1:8000/ws/queue/1?token=PASTE_ACCESS_TOKEN");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
ws.onclose = (e) => console.log("closed", e.code);
// personal notifications (booked / rescheduled / cancelled / "You are next")
const n = new WebSocket("ws://127.0.0.1:8000/ws/notifications?token=PASTE_ACCESS_TOKEN");
n.onmessage = (e) => console.log(JSON.parse(e.data));
```

**Postman:** *New → WebSocket*, URL `ws://127.0.0.1:8000/ws/queue/1?token=<ACCESS_TOKEN>`, press **Connect**; the current queue arrives immediately. Send `ping` to receive `pong`.

Queue message:
```json
{"type":"queue_update","doctor_id":1,"date":"2026-10-19","current_token":1,"waiting_count":2,
 "waiting_tokens":[2,3],"your_token":2,"your_queue_position":1,"estimated_wait_minutes":30}
```
`your_*` fields appear for patients who are waiting. Estimated wait = (patients ahead + the one in consultation) × slot length.
To see live updates: check a patient in (`PUT /appointments/{id}/check-in`) or call the next patient (`PUT /doctors/me/call-next`).

## 17. SMTP configuration and mock e-mail

* **Mock mode (default):** `MAIL_MODE=mock`. No network; each e-mail is logged as `[MOCK EMAIL] to=a***@example.com subject=...` (recipient masked, body never logged).
* **Real e-mail:** set `MAIL_MODE=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS=true`. For Gmail, create an *App Password* (normal passwords are rejected).
* E-mails are sent in the background after the response. A failure (bad credentials, server down, missing settings) is logged and **never undoes** the booking, cancellation or consultation. Passwords, tokens and message bodies are never logged.

E-mails: booking, reschedule, cancellation, doctor-leave cancellation, consultation completed, appointment reminder, follow-up reminder.

## 18. Scheduled jobs

Started and stopped automatically by the FastAPI lifespan (disable with `SCHEDULER_ENABLED=false`).

| Job | Schedule | Behaviour |
|---|---|---|
| Appointment reminders | every hour | `BOOKED` appointments starting within 24 hours; `reminder_sent` is set only after a successful send, so failures are retried and nothing is sent twice |
| No-show detection | every 15 minutes | marks `BOOKED` appointments `NO_SHOW` after slot + 15 min, updates history and the live queue |
| Follow-up reminders | daily 09:00 | e-mails patients whose follow-up date is tomorrow |

Run only **one** server process with the scheduler enabled (e.g. avoid `--workers 4`), or jobs will run once per worker.

## 19. File upload and PDF download

```powershell
curl.exe -X POST "http://127.0.0.1:8000/appointments/1/files" `
  -H "Authorization: Bearer $pat" -F "file=@C:\reports\blood-test.pdf;type=application/pdf"
```
* Allowed: PDF, JPG/JPEG, PNG; max 5 MB (`413` if bigger, `415` for other types or when the file content does not match the extension).
* Stored as `uploads/<uuid>.<ext>`; the original name is kept in the database and used on download.
* Patients upload `LAB_REPORT` to their own appointments; doctors upload `PRESCRIPTION` (default) or `SCAN` (`-F "category=SCAN"`).
* Download: `GET /files/{id}/download` (owner patient, assigned doctor, admin).
* Prescription PDF: `GET /appointments/{id}/prescription-pdf` after the consultation is saved. Created in `generated_pdfs/` (git-ignored) and re-created automatically if missing.

## 20. Reports and ratings

* `GET /reports/dashboard`: today's totals by status and revenue (completed consultations only).
* `GET /reports/doctor-performance?date_from=&date_to=`: appointments, completed, cancelled, no-shows, no-show % (of non-cancelled appointments), revenue per doctor.
* `GET /reports/department-summary`: appointment counts per department.
* `GET /reports/peak-hours`: appointments per hour of the day (cancelled excluded).
* `GET /reports/frequent-no-shows`: patients with ≥ 3 no-shows in the previous 90 days.
* Default report range is the last 30 days; max 366 days; `date_from > date_to` → 400.
* Ratings: `POST /appointments/{id}/rating` (`rating` 1–5, optional `review`) only by the patient who owns a **completed** appointment, once per appointment (409 on duplicates). `GET /doctors/{id}/ratings` returns the average, total and a paginated list.

## 21. Troubleshooting

| Problem | Fix |
|---|---|
| `DATABASE_URL is not set` | Create `.env` from `.env.example` |
| `Access denied for user` / `Unknown database` | Re-check section 7 and the URL in `.env` (URL-encode special characters) |
| `cryptography` error with MySQL 8 | `pip install cryptography` (already in requirements) |
| `alembic upgrade head` cannot connect | MySQL not running, wrong port, or wrong credentials |
| `JWT_SECRET_KEY is not set` | Set it in `.env` |
| Cannot log in as admin | Check `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` in `.env` (password 8+ characters, phone 10 digits), restart uvicorn and read the startup log. Changing the password in `.env` later does not change an admin that already exists |
| `401` on every call | Token expired (30 min): call `/auth/refresh` or log in again; send `Authorization: Bearer <token>` |
| `403` | Your role is not allowed for that endpoint |
| `409` when booking | Slot taken, you already booked that doctor that day, or you have another appointment at that time |
| No e-mails arrive | `MAIL_MODE` is `mock`; or check the logs for the SMTP error |
| WebSocket closes with 1008 | Invalid/expired token or unknown doctor ID |
| PowerShell blocks `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `bcrypt` / `passlib` version warning | Keep the pinned `bcrypt==4.0.1` from requirements.txt |
| Jobs run twice | Run a single worker or disable the scheduler on extra workers |

## 22. Security considerations and assumptions

* Passwords hashed with bcrypt; refresh tokens stored only as SHA-256 hashes; login errors do not reveal whether an e-mail exists.
* Secrets come from `.env`; `.env`, uploads and generated PDFs are git-ignored.
* Uploads are checked by extension, content type and file signature, stored under random UUID names (no path traversal), and served only to authorized users.
* Database errors and stack traces are never returned to clients (generic 500, details only in server logs).
* Double booking is prevented by row locking on the doctor and by unique constraints (`uq_doctor_slot`, `uq_patient_doctor_day`, `uq_patient_slot`). A cancelled appointment sets `slot_active` to `NULL`, which frees its slot.
* Times: appointment dates/times are in the hospital time zone (`TIMEZONE`); audit timestamps are UTC.
* Assumptions: one hospital; a doctor has one profile; slots are in whole minutes; patients can also check themselves in (same 30-minute window) in addition to admins; a doctor's login is deactivated together with the doctor profile; recording a consultation is not possible for appointments that were never called into consultation.
* Put the API behind HTTPS and restrict CORS/hosts before any real deployment. This is a learning/portfolio project, not a certified medical system.
