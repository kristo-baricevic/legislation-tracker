import pytest

from apps.ingestion import committee_sources

HOUSE_XML = b"""<?xml version='1.0'?>
<MemberData publish-date="January 5, 2026">
  <title-info><congress-num>119</congress-num><majority>R</majority></title-info>
  <committees>
    <committee comcode="II00"><committee-fullname>Rules</committee-fullname>
      <subcommittee subcomcode="II01"><subcommittee-fullname>Procedure</subcommittee-fullname></subcommittee>
    </committee>
  </committees>
  <members>
    <member><member-info><bioguideID>R000001</bioguideID><caucus>R</caucus></member-info>
      <committee-assignments><committee comcode="II00" rank="1" leadership="Chair"/><subcommittee subcomcode="II01" rank="2"/></committee-assignments>
    </member>
    <member><member-info><bioguideID>R000002</bioguideID><caucus>D</caucus></member-info>
      <committee-assignments><committee comcode="II00" rank="1" leadership="Ranking Member"/></committee-assignments>
    </member>
  </members>
</MemberData>"""

SENATE_XML = b"""<?xml version='1.0'?>
<senators><lastUpdate><date>Monday, January 5, 2026</date><time>5:00:08 AM EST</time></lastUpdate>
  <senator><party>R</party><bioguideId>S000001</bioguideId><committees>
    <committee code="SSFI00">Committee on Finance</committee>
    <committee code="SPAG00">Special Committee on Aging</committee>
  </committees></senator>
</senators>"""


def test_house_roster_preserves_bioguide_ids_roles_and_parent_identity():
    snapshot = committee_sources.parse_house_committee_roster(
        HOUSE_XML, source_url="https://source.test/house.xml"
    )

    assert snapshot.congress == 119
    assert {
        (item.bioguide_id, item.committee_code) for item in snapshot.assignments
    } == {
        ("R000001", "hsii00"),
        ("R000001", "hsii01"),
        ("R000002", "hsii00"),
    }
    subcommittee = next(
        item for item in snapshot.assignments if item.committee_code == "hsii01"
    )
    assert (subcommittee.parent_code, subcommittee.parent_name, subcommittee.role) == (
        "hsii00",
        "Rules",
        "member",
    )
    assert (
        next(
            item for item in snapshot.assignments if item.bioguide_id == "R000002"
        ).role
        == "ranking_member"
    )


def test_senate_roster_uses_official_member_bioguide_ids_without_name_matching():
    snapshot = committee_sources.parse_senate_committee_roster(
        SENATE_XML, congress=119, source_url="https://source.test/senate.xml"
    )

    assert snapshot.chamber == "senate"
    assert {
        (item.bioguide_id, item.committee_code, item.party_side)
        for item in snapshot.assignments
    } == {
        ("S000001", "ssfi00", "R"),
        ("S000001", "spag00", "R"),
    }


@pytest.mark.parametrize(
    ("source", "chamber", "raw_code", "expected"),
    [
        ("house", "house", "II00", "hsii00"),
        ("house", "house", "HSII01", "hsii01"),
        ("senate", "senate", "SSFI00", "ssfi00"),
        ("senate", "senate", "SPAG00", "spag00"),
        ("senate", "senate", "JCSE00", "jcse00"),
        ("congress", "house", "HSII00", "hsii00"),
    ],
)
def test_normalize_committee_system_code(source, chamber, raw_code, expected):
    assert (
        committee_sources.normalize_committee_system_code(
            source=source, chamber=chamber, raw_code=raw_code
        )
        == expected
    )


def test_roster_rejects_external_entities_and_missing_bioguide_ids():
    with pytest.raises(committee_sources.CommitteeRosterError):
        committee_sources.parse_house_committee_roster(
            b"<!DOCTYPE value [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><MemberData />",
            source_url="https://source.test/house.xml",
        )
    invalid = HOUSE_XML.replace(b"<bioguideID>R000001</bioguideID>", b"")
    with pytest.raises(committee_sources.CommitteeRosterError, match="Bioguide"):
        committee_sources.parse_house_committee_roster(
            invalid, source_url="https://source.test/house.xml"
        )


def test_download_enforces_content_type_and_byte_limit(monkeypatch, settings):
    class Response:
        ok = True
        status_code = 200
        headers = {"Content-Type": "application/xml"}
        closed = False

        def iter_content(self, chunk_size):
            yield b"1234"
            yield b"5678"

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(
        committee_sources.requests, "get", lambda *args, **kwargs: response
    )
    settings.COMMITTEE_ROSTER_MAX_BYTES = 7

    with pytest.raises(committee_sources.CommitteeRosterError, match="byte limit"):
        committee_sources._download_xml(url="https://source.test/roster.xml")
    assert response.closed is True
