from uuid import UUID

from app.utils import new_id


def test_new_id_is_uuid_v7():
    value = UUID(new_id())
    assert value.version == 7
