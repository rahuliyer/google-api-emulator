from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token"}
PEOPLE = "/services/people/v1"


def test_connections_requires_person_fields(client: TestClient):
    response = client.get(f"{PEOPLE}/people/me/connections", headers=AUTH)
    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_list_connections(client: TestClient):
    response = client.get(
        f"{PEOPLE}/people/me/connections",
        params={"personFields": "names,emailAddresses"},
        headers=AUTH,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["totalPeople"] == 1
    assert body["connections"][0]["resourceName"] == "people/c1"
    assert body["connections"][0]["names"][0]["givenName"] == "Bob"
    assert "etag" in body["connections"][0]
    assert "metadata" in body["connections"][0]
    assert "phoneNumbers" not in body["connections"][0]


def test_connections_pagination(client: TestClient):
    created = client.post(
        f"{PEOPLE}/people:createContact",
        json={"names": [{"givenName": "Dana", "displayName": "Dana"}]},
        headers=AUTH,
    )
    assert created.status_code == 200
    first = client.get(
        f"{PEOPLE}/people/me/connections",
        params={"personFields": "names", "pageSize": 1},
        headers=AUTH,
    )
    assert first.status_code == 200
    assert len(first.json()["connections"]) == 1
    assert "nextPageToken" in first.json()
    second = client.get(
        f"{PEOPLE}/people/me/connections",
        params={
            "personFields": "names",
            "pageSize": 1,
            "pageToken": first.json()["nextPageToken"],
        },
        headers=AUTH,
    )
    assert second.status_code == 200
    assert len(second.json()["connections"]) == 1
    assert "nextPageToken" not in second.json()
    names = {
        first.json()["connections"][0]["names"][0]["givenName"],
        second.json()["connections"][0]["names"][0]["givenName"],
    }
    assert names == {"Bob", "Dana"}


def test_get_me_and_contact(client: TestClient):
    me = client.get(
        f"{PEOPLE}/people/me",
        params={"personFields": "names"},
        headers=AUTH,
    )
    assert me.status_code == 200
    assert me.json()["names"][0]["givenName"] == "Alice"
    contact = client.get(
        f"{PEOPLE}/people/c1",
        params={"personFields": "names,emailAddresses,phoneNumbers"},
        headers=AUTH,
    )
    assert contact.status_code == 200
    assert contact.json()["emailAddresses"][0]["value"] == "bob@example.com"


def test_get_unknown_contact_is_not_found(client: TestClient):
    response = client.get(
        f"{PEOPLE}/people/does-not-exist",
        params={"personFields": "names"},
        headers=AUTH,
    )
    assert response.status_code == 404
    assert response.json()["error"]["status"] == "NOT_FOUND"


def test_batch_get(client: TestClient):
    response = client.get(
        f"{PEOPLE}/people:batchGet",
        params=[
            ("resourceNames", "people/me"),
            ("resourceNames", "people/c1"),
            ("resourceNames", "people/missing"),
            ("personFields", "names"),
        ],
        headers=AUTH,
    )
    assert response.status_code == 200
    responses = response.json()["responses"]
    assert responses[0]["httpStatusCode"] == 200
    assert responses[0]["person"]["names"][0]["givenName"] == "Alice"
    assert responses[1]["httpStatusCode"] == 200
    assert responses[2]["httpStatusCode"] == 404
    assert responses[2]["status"]["code"] == 5


def test_create_contact_rejects_duplicate_names(client: TestClient):
    response = client.post(
        f"{PEOPLE}/people:createContact",
        json={"names": [{"givenName": "A"}, {"givenName": "B"}]},
        headers=AUTH,
    )
    assert response.status_code == 400


def test_create_update_delete_contact(client: TestClient):
    created = client.post(
        f"{PEOPLE}/people:createContact",
        params={"personFields": "names,emailAddresses"},
        json={
            "names": [{"givenName": "Eve", "familyName": "Lee", "displayName": "Eve Lee"}],
            "emailAddresses": [{"value": "eve@example.com"}],
        },
        headers=AUTH,
    )
    assert created.status_code == 200
    person = created.json()
    assert person["resourceName"].startswith("people/")
    assert person["etag"]
    resource_id = person["resourceName"].split("/", 1)[1]

    updated = client.patch(
        f"{PEOPLE}/people/{resource_id}:updateContact",
        params={"updatePersonFields": "emailAddresses", "personFields": "names,emailAddresses"},
        json={"etag": person["etag"], "emailAddresses": [{"value": "eve.lee@example.com"}]},
        headers=AUTH,
    )
    assert updated.status_code == 200
    assert updated.json()["emailAddresses"][0]["value"] == "eve.lee@example.com"
    assert updated.json()["etag"] != person["etag"]
    assert updated.json()["names"][0]["givenName"] == "Eve"

    stale = client.patch(
        f"{PEOPLE}/people/{resource_id}:updateContact",
        params={"updatePersonFields": "emailAddresses"},
        json={"etag": person["etag"], "emailAddresses": [{"value": "stale@example.com"}]},
        headers=AUTH,
    )
    assert stale.status_code == 400

    deleted = client.delete(
        f"{PEOPLE}/people/{resource_id}:deleteContact",
        headers=AUTH,
    )
    assert deleted.status_code == 200
    assert deleted.json() == {}
    missing = client.get(
        f"{PEOPLE}/people/{resource_id}",
        params={"personFields": "names"},
        headers=AUTH,
    )
    assert missing.status_code == 404


def test_update_requires_etag(client: TestClient):
    response = client.patch(
        f"{PEOPLE}/people/c1:updateContact",
        params={"updatePersonFields": "emailAddresses"},
        json={"emailAddresses": [{"value": "no-etag@example.com"}]},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_reset_restores_fixture_contacts(client: TestClient):
    client.delete(f"{PEOPLE}/people/c1:deleteContact", headers=AUTH)
    assert (
        client.get(
            f"{PEOPLE}/people/c1",
            params={"personFields": "names"},
            headers=AUTH,
        ).status_code
        == 404
    )
    client.post("/reset")
    restored = client.get(
        f"{PEOPLE}/people/c1",
        params={"personFields": "names"},
        headers=AUTH,
    )
    assert restored.status_code == 200
    assert restored.json()["names"][0]["givenName"] == "Bob"
