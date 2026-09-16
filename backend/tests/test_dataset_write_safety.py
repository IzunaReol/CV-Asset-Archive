import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.routers import datasets
from app.schemas import DatasetRestoreRequest


def test_restore_rolls_back_members_on_insert_failure(monkeypatch):
    backup=[{'id':'old','dataset_id':'dataset','asset_id':'old-asset'}]
    members=[{'asset_id':'asset'}]
    membership=SimpleNamespace(find=lambda query:SimpleNamespace(to_list=AsyncMock(return_value=backup)),delete_many=AsyncMock(),insert_many=AsyncMock(side_effect=[RuntimeError('storage failed'),None]))
    database=SimpleNamespace(datasets=SimpleNamespace(find_one=AsyncMock(return_value={'id':'dataset'}),update_one=AsyncMock()),dataset_versions=SimpleNamespace(find_one=AsyncMock(return_value={'id':'version'})),dataset_version_memberships=SimpleNamespace(find=lambda query:SimpleNamespace(to_list=AsyncMock(return_value=members))),dataset_memberships=membership,assets=SimpleNamespace(distinct=AsyncMock(return_value=['asset'])))
    monkeypatch.setattr(datasets,'db',database)
    with pytest.raises(RuntimeError,match='storage failed'):
        asyncio.run(datasets.restore_version.__wrapped__('dataset',DatasetRestoreRequest(version_id='version'),SimpleNamespace(state=SimpleNamespace(request_id='test')),{'id':'user'}))
    assert membership.delete_many.await_count==2
    assert membership.insert_many.call_args.args[0]==backup


def test_write_guard_releases_lock_on_failure(monkeypatch):
    update=AsyncMock(return_value=SimpleNamespace(modified_count=1))
    monkeypatch.setattr(datasets,'db',SimpleNamespace(datasets=SimpleNamespace(update_one=update)))
    @datasets.serialize_dataset_write
    async def operation(dataset_id):
        raise RuntimeError('failed')
    with pytest.raises(RuntimeError):
        asyncio.run(operation('dataset'))
    assert update.await_count==2
    assert '$unset' in update.call_args.args[1]
