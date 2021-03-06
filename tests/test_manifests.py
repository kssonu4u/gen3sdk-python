import asyncio
import os
import glob
import sys
import shutil
import logging
from unittest.mock import MagicMock, patch

from gen3.tools.indexing import verify_object_manifest
from gen3.tools.indexing import download_manifest
from gen3.tools.indexing.download_manifest import _get_records_and_write_to_file
from gen3.tools.indexing.download_manifest import TMP_FOLDER
from gen3.tools.indexing import async_download_object_manifest


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))


@patch("gen3.tools.indexing.verify_manifest.Gen3Index")
def test_verify_manifest(mock_index):
    """
    Test that verify manifest function correctly writes out log file
    with expected error information.

    NOTE: records in indexd are mocked
    """
    mock_index.return_value.get_record.side_effect = _mock_get_guid
    verify_object_manifest(
        "http://localhost",
        CURRENT_DIR + "/test_manifest.csv",
        num_processes=3,
        log_output_filename="test.log",
    )

    logs = {}
    try:
        with open("test.log") as file:
            for line in file:
                guid, error, expected, actual = line.split("|")
                logs.setdefault(guid, {})[error] = {
                    "expected": expected.split("expected ")[1],
                    "actual": actual.split("actual ")[1],
                }
    except Exception:
        # unexpected file format, fail test
        assert False

    # everything in indexd is mocked to be correct for this one
    assert "dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b" not in logs

    assert "dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2" in logs
    assert "dg.TEST/9c205cd7-c399-4503-9f49-5647188bde66" in logs

    # ensure logs exist for fields that are mocked to be incorrect in indexd
    assert "/programs/DEV/projects/test2" in logs[
        "dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2"
    ].get("authz", {}).get("expected")
    assert "DEV" in logs["dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2"].get(
        "acl", {}
    ).get("expected")
    assert "235" in logs["dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2"].get(
        "file_size", {}
    ).get("expected")
    assert "c1234567891234567890123456789012" in logs[
        "dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2"
    ].get("md5", {}).get("expected")
    assert "gs://test/test3.txt" in logs[
        "dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2"
    ].get("urls", {}).get("expected")

    # make sure error exists when record doesnt exist in indexd
    assert "no_record" in logs["dg.TEST/9c205cd7-c399-4503-9f49-5647188bde66"]


def test_download_manifest(monkeypatch, gen3_index):
    """
    Test that dowload manifest generates a file with expected content.
    """
    rec1 = gen3_index.create_record(
        did="dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b",
        hashes={"md5": "a1234567891234567890123456789012"},
        size=123,
        acl=["DEV", "test"],
        authz=["/programs/DEV/projects/test"],
        urls=["s3://testaws/aws/test.txt", "gs://test/test.txt"],
    )
    rec2 = gen3_index.create_record(
        did="dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2",
        hashes={"md5": "b1234567891234567890123456789012"},
        size=234,
        acl=["DEV", "test2"],
        authz=["/programs/DEV/projects/test2", "/programs/DEV/projects/test2bak"],
        urls=["gs://test/test.txt"],
        file_name="test.txt",
    )
    rec3 = gen3_index.create_record(
        did="dg.TEST/ed8f4658-6acd-4f96-9dd8-3709890c959e",
        hashes={"md5": "e1234567891234567890123456789012"},
        size=345,
        acl=["DEV", "test3"],
        authz=["/programs/DEV/projects/test3", "/programs/DEV/projects/test3bak"],
        urls=["gs://test/test3.txt"],
    )
    # mock_index.return_value.get_stats.return_value = gen3_index.get("/_stats")

    monkeypatch.setattr(download_manifest, "INDEXD_RECORD_PAGE_SIZE", 2)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(
        async_download_object_manifest(
            "http://localhost:8001",
            output_filename="object-manifest.csv",
            num_processes=1,
        )
    )

    records = {}
    try:
        with open("object-manifest.csv") as file:
            # skip header
            next(file)
            for line in file:
                guid, urls, authz, acl, md5, file_size, file_name = line.split(",")
                guid = guid.strip("\n")
                urls = urls.split(" ")
                authz = authz.split(" ")
                acl = acl.split(" ")
                file_size = file_size.strip("\n")
                file_name = file_name.strip("\n")

                records[guid] = {
                    "urls": urls,
                    "authz": authz,
                    "acl": acl,
                    "md5": md5,
                    "file_size": file_size,
                    "file_name": file_name,
                }
    except Exception:
        # unexpected file format, fail test
        assert False

    # ensure downloaded manifest populates expected info for a record
    assert "gs://test/test.txt" in records.get(
        "dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b", {}
    ).get("urls", [])
    assert "s3://testaws/aws/test.txt" in records.get(
        "dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b", {}
    ).get("urls", [])
    assert "/programs/DEV/projects/test" in records.get(
        "dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b", {}
    ).get("authz", [])
    assert "DEV" in records.get("dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b", {}).get(
        "acl", []
    )
    assert "test" in records.get(
        "dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b", {}
    ).get("acl", [])
    assert "123" in records.get("dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b", {}).get(
        "file_size"
    )
    assert "a1234567891234567890123456789012" in records.get(
        "dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b", {}
    ).get("md5")
    assert not records.get("dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b", {}).get(
        "file_name"
    )

    # assert other 2 records exist
    assert "dg.TEST/ed8f4658-6acd-4f96-9dd8-3709890c959e" in records
    assert "dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2" in records
    assert "test.txt" == records.get(
        "dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2", {}
    ).get("file_name")


def _mock_get_guid(guid, **kwargs):
    if guid == "dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b":
        return {
            "acl": ["DEV", "test"],
            "authz": ["/programs/DEV/projects/test"],
            "baseid": f"'1' + {guid[1:-1]} + '1'",
            "created_date": "2019-11-24T18:29:48.218755",
            "did": f"{guid}",
            "file_name": None,
            "form": "object",
            "hashes": {"md5": "a1234567891234567890123456789012"},
            "metadata": {},
            "rev": "abc123",
            "size": 123,
            "updated_date": "2019-11-24T18:29:48.218761",
            "uploader": None,
            "urls": ["s3://testaws/aws/test.txt", "gs://test/test.txt"],
            "urls_metadata": {
                "gs://test/test.txt": {},
                "s3://testaws/aws/test.txt": {},
            },
            "version": None,
        }
    elif guid == "dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2":
        return {
            "acl": ["DEV", "test2"],
            "authz": [
                "/programs/DEV/projects/test2",
                "/programs/DEV/projects/test2bak",
            ],
            "baseid": f"'1' + {guid[1:-1]} + '1'",
            "created_date": "2019-11-24T18:29:48.218755",
            "did": f"{guid}",
            "file_name": None,
            "form": "object",
            "hashes": {"md5": "b1234567891234567890123456789012"},
            "metadata": {},
            "rev": "abc234",
            "size": 234,
            "updated_date": "2019-11-24T18:29:48.218761",
            "uploader": None,
            "urls": ["gs://test/test.txt"],
            "urls_metadata": {"gs://test/test.txt": {}},
            "version": None,
        }
    else:
        return None


def _mock_get_records_on_page(page, limit, **kwargs):
    # for testing, the limit is 2
    if page == 0:
        return [
            {
                "acl": ["DEV", "test"],
                "authz": ["/programs/DEV/projects/test"],
                "baseid": "1g.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a221",
                "created_date": "2019-11-24T18:29:48.218755",
                "did": "dg.TEST/f2a39f98-6ae1-48a5-8d48-825a0c52a22b",
                "file_name": None,
                "form": "object",
                "hashes": {"md5": "a1234567891234567890123456789012"},
                "metadata": {},
                "rev": "abc123",
                "size": 123,
                "updated_date": "2019-11-24T18:29:48.218761",
                "uploader": None,
                "urls": ["s3://testaws/aws/test.txt", "gs://test/test.txt"],
                "urls_metadata": {
                    "gs://test/test.txt": {},
                    "s3://testaws/aws/test.txt": {},
                },
                "version": None,
            },
            {
                "acl": ["DEV", "test2"],
                "authz": [
                    "/programs/DEV/projects/test2",
                    "/programs/DEV/projects/test2bak",
                ],
                "baseid": "1g.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d1",
                "created_date": "2019-11-24T18:29:48.218755",
                "did": "dg.TEST/1e9d3103-cbe2-4c39-917c-b3abad4750d2",
                "file_name": None,
                "form": "object",
                "hashes": {"md5": "b1234567891234567890123456789012"},
                "metadata": {},
                "rev": "abc234",
                "size": 234,
                "updated_date": "2019-11-24T18:29:48.218761",
                "uploader": None,
                "urls": ["gs://test/test.txt"],
                "urls_metadata": {"gs://test/test.txt": {}},
                "version": None,
            },
        ]
    elif page == 1:
        return [
            {
                "acl": ["DEV", "test3"],
                "authz": [
                    "/programs/DEV/projects/test3",
                    "/programs/DEV/projects/test3bak",
                ],
                "baseid": "1g.TEST/ed8f4658-6acd-4f96-9dd8-3709890c9591",
                "created_date": "2019-11-24T18:29:48.218755",
                "did": "dg.TEST/ed8f4658-6acd-4f96-9dd8-3709890c959e",
                "file_name": None,
                "form": "object",
                "hashes": {"md5": "e1234567891234567890123456789012"},
                "metadata": {},
                "rev": "abc345",
                "size": 345,
                "updated_date": "2019-11-24T18:29:48.218761",
                "uploader": None,
                "urls": ["gs://test/test3.txt"],
                "urls_metadata": {"gs://test/test3.txt": {}},
                "version": None,
            }
        ]
    else:
        return []
