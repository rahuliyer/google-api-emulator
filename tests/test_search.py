from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token"}
PEOPLE = "/services/people/v1"


def test_search_warmup_empty_query(client: TestClient):
    response = client.get(
        f"{PEOPLE}/people:searchContacts",
        params={"query": "", "readMask": "names,emailAddresses"},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_search_contacts_prefix(client: TestClient):
    hits = client.get(
        f"{PEOPLE}/people:searchContacts",
        params={"query": "Bo", "readMask": "names,emailAddresses"},
        headers=AUTH,
    )
    assert hits.status_code == 200
    people = [item["person"] for item in hits.json()["results"]]
    assert people[0]["names"][0]["givenName"] == "Bob"
    assert "phoneNumbers" not in people[0]

    phrase = client.get(
        f"{PEOPLE}/people:searchContacts",
        params={"query": "Bob J", "readMask": "names"},
        headers=AUTH,
    )
    assert phrase.json()["results"][0]["person"]["names"][0]["displayName"] == "Bob Jones"

    word = client.get(
        f"{PEOPLE}/people:searchContacts",
        params={"query": "Jon", "readMask": "names"},
        headers=AUTH,
    )
    assert word.json()["results"][0]["person"]["names"][0]["familyName"] == "Jones"

    miss = client.get(
        f"{PEOPLE}/people:searchContacts",
        params={"query": "ob J", "readMask": "names"},
        headers=AUTH,
    )
    assert miss.json()["results"] == []


def test_search_requires_query(client: TestClient):
    response = client.get(
        f"{PEOPLE}/people:searchContacts",
        params={"readMask": "names"},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_search_requires_read_mask(client: TestClient):
    response = client.get(
        f"{PEOPLE}/people:searchContacts",
        params={"query": "Bob"},
        headers=AUTH,
    )
    assert response.status_code == 400


def test_list_other_contacts(client: TestClient):
    response = client.get(
        f"{PEOPLE}/otherContacts",
        params={"readMask": "names,emailAddresses"},
        headers=AUTH,
    )
    assert response.status_code == 200
    others = response.json()["otherContacts"]
    assert others[0]["resourceName"] == "otherContacts/o1"
    assert others[0]["names"][0]["displayName"] == "Carol"
    assert others[0]["emailAddresses"][0]["value"] == "carol@example.com"


def test_search_other_contacts(client: TestClient):
    warmup = client.get(
        f"{PEOPLE}/otherContacts:search",
        params={"query": "", "readMask": "names,emailAddresses"},
        headers=AUTH,
    )
    assert warmup.json() == {"results": []}
    hits = client.get(
        f"{PEOPLE}/otherContacts:search",
        params={"query": "car", "readMask": "names,emailAddresses"},
        headers=AUTH,
    )
    assert hits.status_code == 200
    assert hits.json()["results"][0]["person"]["emailAddresses"][0]["value"] == "carol@example.com"
