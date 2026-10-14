from tests.conftest import PASSWORD, auth, book, future_weekday


def test_department_crud_and_unique_name(client, admin_headers, register_patient):
    created = client.post("/departments", json={"name": "Neurology"}, headers=admin_headers)
    assert created.status_code == 201
    dept_id = created.json()["id"]
    assert client.post("/departments", json={"name": "neurology"}, headers=admin_headers).status_code == 409

    listing = client.get("/departments?skip=0&limit=10", headers=admin_headers).json()
    assert listing["total"] == 1 and listing["items"][0]["name"] == "Neurology"

    updated = client.put(f"/departments/{dept_id}", json={"description": "Brain"}, headers=admin_headers)
    assert updated.status_code == 200 and updated.json()["description"] == "Brain"

    patient = register_patient()
    assert client.post("/departments", json={"name": "X-Ray"}, headers=patient).status_code == 403
    assert client.delete(f"/departments/{dept_id}", headers=patient).status_code == 403
    assert client.delete(f"/departments/{dept_id}", headers=admin_headers).status_code == 200
    assert client.delete(f"/departments/{dept_id}", headers=admin_headers).status_code == 404


def test_department_with_active_doctor_cannot_be_deleted(client, admin_headers, setup_doctor):
    setup_doctor()
    dept_id = client.get("/departments", headers=admin_headers).json()["items"][0]["id"]
    assert client.delete(f"/departments/{dept_id}", headers=admin_headers).status_code == 400


def test_doctor_validation_rules(client, admin_headers):
    dept = client.post("/departments", json={"name": "ENT"}, headers=admin_headers).json()["id"]
    user = client.post(
        "/auth/users",
        json={"email": "d@test.com", "password": PASSWORD, "full_name": "Dr Dee", "phone": "9876543210", "role": "DOCTOR"},
        headers=admin_headers,
    ).json()["id"]
    good = {
        "user_id": user, "department_id": dept, "specialization": "ENT", "qualification": "MS",
        "experience_years": 3, "consultation_fee": 300, "slot_duration_minutes": 15,
    }
    assert client.post("/doctors", json={**good, "slot_duration_minutes": 25}, headers=admin_headers).status_code == 422
    assert client.post("/doctors", json={**good, "consultation_fee": 0}, headers=admin_headers).status_code == 422
    assert client.post("/doctors", json={**good, "experience_years": -1}, headers=admin_headers).status_code == 422
    assert client.post("/doctors", json=good, headers=admin_headers).status_code == 201
    assert client.post("/doctors", json=good, headers=admin_headers).status_code == 409  # one profile per user


def test_doctor_filters_and_patient_sees_only_active(client, admin_headers, setup_doctor, register_patient):
    first = setup_doctor("a@test.com", "Alice Heart", dept_name="Cardiology")
    setup_doctor("b@test.com", "Bob Bones", dept_name="Orthopedics")

    patient = register_patient()
    assert client.get("/doctors", headers=patient).json()["total"] == 2
    assert client.get("/doctors?name=alice", headers=patient).json()["total"] == 1
    assert client.get("/doctors?specialization=cardio", headers=patient).json()["total"] == 2
    assert client.get("/doctors?limit=1", headers=patient).json()["items"].__len__() == 1

    assert client.delete(f"/doctors/{first}", headers=admin_headers).status_code == 200
    assert client.get("/doctors", headers=patient).json()["total"] == 1          # soft deleted
    assert client.get(f"/doctors/{first}", headers=patient).status_code == 404
    assert client.get("/doctors?include_inactive=true", headers=admin_headers).json()["total"] == 2
    assert client.get(f"/doctors/{first}", headers=admin_headers).json()["is_active"] is False


def test_doctor_with_upcoming_appointments_cannot_be_deactivated(client, admin_headers, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    assert book(client, register_patient(), doctor_id, future_weekday(3)).status_code == 201
    assert client.delete(f"/doctors/{doctor_id}", headers=admin_headers).status_code == 400
    assert client.put(f"/doctors/{doctor_id}", json={"is_active": False}, headers=admin_headers).status_code == 400
