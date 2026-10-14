from app.config import settings
from tests.conftest import auth, book, future_weekday

PDF = b"%PDF-1.4\n%test file\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def _appointment(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    patient = register_patient()
    appointment = book(client, patient, doctor_id, future_weekday(3), "09:00").json()
    return appointment, patient


def test_patient_uploads_pdf_and_downloads_original_name(client, setup_doctor, register_patient):
    appointment, patient = _appointment(client, setup_doctor, register_patient)
    url = f"/appointments/{appointment['id']}/files"
    response = client.post(url, files={"file": ("my report.pdf", PDF, "application/pdf")}, headers=patient)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["original_filename"] == "my report.pdf" and data["category"] == "LAB_REPORT"

    stored = list(settings.UPLOAD_DIR.iterdir())
    assert any(path.suffix == ".pdf" and path.name != "my report.pdf" and len(path.stem) == 32 for path in stored)

    download = client.get(f"/files/{data['id']}/download", headers=patient)
    assert download.status_code == 200 and download.content == PDF
    assert client.get(url, headers=patient).json()["total"] == 1


def test_same_filename_twice_never_overwrites(client, setup_doctor, register_patient):
    appointment, patient = _appointment(client, setup_doctor, register_patient)
    url = f"/appointments/{appointment['id']}/files"
    first = client.post(url, files={"file": ("a.png", PNG, "image/png")}, headers=patient).json()
    second = client.post(url, files={"file": ("a.png", PNG + b"1", "image/png")}, headers=patient).json()
    assert first["id"] != second["id"]
    assert len({p.name for p in settings.UPLOAD_DIR.iterdir()}) == 2


def test_file_type_and_size_validation(client, setup_doctor, register_patient):
    appointment, patient = _appointment(client, setup_doctor, register_patient)
    url = f"/appointments/{appointment['id']}/files"
    assert client.post(url, files={"file": ("virus.exe", b"MZ", "application/octet-stream")}, headers=patient).status_code == 415
    assert client.post(url, files={"file": ("fake.pdf", b"not really a pdf", "application/pdf")}, headers=patient).status_code == 415
    assert client.post(url, files={"file": ("x.png", PNG, "application/pdf")}, headers=patient).status_code == 415

    too_big = PDF + b"0" * (5 * 1024 * 1024)
    assert client.post(url, files={"file": ("big.pdf", too_big, "application/pdf")}, headers=patient).status_code == 413
    exactly_limit = PDF + b"0" * (5 * 1024 * 1024 - len(PDF))
    assert client.post(url, files={"file": ("ok.pdf", exactly_limit, "application/pdf")}, headers=patient).status_code == 201
    # failed uploads leave nothing behind
    assert len(list(settings.UPLOAD_DIR.iterdir())) == 1


def test_file_ownership_and_roles(client, setup_doctor, register_patient, admin_headers):
    appointment, patient = _appointment(client, setup_doctor, register_patient)
    stranger = register_patient("s@test.com", phone="9000000008")
    doctor = auth(client, "doc@test.com")
    url = f"/appointments/{appointment['id']}/files"

    assert client.post(url, files={"file": ("a.pdf", PDF, "application/pdf")}, headers=stranger).status_code == 403
    assert client.post(url, files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 401
    assert client.post(url, files={"file": ("a.pdf", PDF, "application/pdf")}, headers=admin_headers).status_code == 403

    uploaded = client.post(url, files={"file": ("a.pdf", PDF, "application/pdf")}, headers=patient).json()
    assert client.get(f"/files/{uploaded['id']}/download", headers=stranger).status_code == 403
    assert client.get(f"/files/{uploaded['id']}/download", headers=doctor).status_code == 200     # assigned doctor
    assert client.get(f"/files/{uploaded['id']}/download", headers=admin_headers).status_code == 200
    assert client.get("/files/9999/download", headers=patient).status_code == 404
    assert client.get(url, headers=stranger).status_code == 403

    # patients may only upload lab reports; doctors may upload scans/prescriptions
    assert client.post(url, files={"file": ("a.pdf", PDF, "application/pdf")}, data={"category": "SCAN"}, headers=patient).status_code == 403
    scan = client.post(url, files={"file": ("scan.png", PNG, "image/png")}, data={"category": "SCAN"}, headers=doctor)
    assert scan.status_code == 201 and scan.json()["category"] == "SCAN"
    assert client.post(url, files={"file": ("a.pdf", PDF, "application/pdf")}, data={"category": "LAB_REPORT"}, headers=doctor).status_code == 403
