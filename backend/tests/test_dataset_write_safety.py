import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.routers import datasets
from app.schemas import DatasetRestoreRequest


def test_restore_rolls_back_members_on_insert_failure(monkeypatch):
    backup=[{'id':'old','dataset_id':'dataset','asset_id':'old-asset'}]
    members=[{'asset_id':'asset','snapshot':{'type':'image'}}]
    membership=SimpleNamespace(find=lambda query:SimpleNamespace(to_list=AsyncMock(return_value=backup)),delete_many=AsyncMock(),insert_many=AsyncMock(side_effect=[RuntimeError('storage failed'),None]))
    database=SimpleNamespace(datasets=SimpleNamespace(find_one=AsyncMock(return_value={'id':'dataset'}),update_one=AsyncMock()),dataset_versions=SimpleNamespace(find_one=AsyncMock(return_value={'id':'version'})),dataset_version_memberships=SimpleNamespace(find=lambda query:SimpleNamespace(to_list=AsyncMock(return_value=members))),dataset_memberships=membership,assets=SimpleNamespace(distinct=AsyncMock(return_value=['asset'])))
    monkeypatch.setattr(datasets,'db',database)
    with pytest.raises(RuntimeError,match='storage failed'):
        asyncio.run(datasets.restore_version.__wrapped__('dataset',DatasetRestoreRequest(version_id='version'),SimpleNamespace(state=SimpleNamespace(request_id='test')),{'id':'user'}))
    assert membership.delete_many.await_count==2
    assert membership.insert_many.call_args.args[0]==backup


def test_write_guard_releases_lock_on_failure(monkeypatch):
    update=AsyncMock(return_value=SimpleNamespace(modified_count=1))
    monkeypatch.setattr(datasets,'db',SimpleNamespace(datasets=SimpleNamespace(update_one=update,find_one=AsyncMock(return_value=None))))
    @datasets.serialize_dataset_write
    async def operation(dataset_id):
        raise RuntimeError('failed')
    with pytest.raises(RuntimeError):
        asyncio.run(operation('dataset'))
    assert update.await_count==2
    assert '$unset' in update.call_args.args[1]


def test_write_guard_can_take_expired_lock(monkeypatch):
    update = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    monkeypatch.setattr(datasets, 'db', SimpleNamespace(datasets=SimpleNamespace(update_one=update,find_one=AsyncMock(return_value=None))))

    @datasets.serialize_dataset_write
    async def operation(dataset_id):
        return 'ok'

    assert asyncio.run(operation('dataset')) == 'ok'
    lock_filter = update.call_args_list[0].args[0]
    assert {'write_token': None} in lock_filter['$or']
    assert any('write_token_expires_at' in clause for clause in lock_filter['$or'])
    assert update.call_args_list[-1].args[1]['$unset'] == {
        'write_token': '', 'write_token_expires_at': '',
    }


def test_pending_restore_is_replayed_before_next_write(monkeypatch):
    members = [
        {'asset_id': 'image', 'snapshot': {'type': 'image'}},
        {'asset_id': 'annotation', 'snapshot': {'type': 'annotation'}},
    ]
    memberships = SimpleNamespace(delete_many=AsyncMock(), insert_many=AsyncMock())
    datasets_collection = SimpleNamespace(
        find_one=AsyncMock(return_value={'restore_target_version_id': 'version', 'restore_actor_id': 'user'}),
        update_one=AsyncMock(),
    )
    database = SimpleNamespace(
        datasets=datasets_collection,
        dataset_versions=SimpleNamespace(find_one=AsyncMock(return_value={'id': 'version'})),
        dataset_version_memberships=SimpleNamespace(
            find=lambda query: SimpleNamespace(to_list=AsyncMock(return_value=members))
        ),
        dataset_memberships=memberships,
    )
    monkeypatch.setattr(datasets, 'db', database)
    sync = AsyncMock()
    monkeypatch.setattr(datasets, 'sync_annotation_memberships', sync)

    asyncio.run(datasets._resume_pending_restore('dataset'))

    assert [item['asset_id'] for item in memberships.insert_many.call_args.args[0]] == ['image']
    sync.assert_awaited_once_with('dataset', 'user')
    assert datasets_collection.update_one.call_args.args[1]['$unset'] == {
        'restore_target_version_id': '', 'restore_actor_id': '',
    }
