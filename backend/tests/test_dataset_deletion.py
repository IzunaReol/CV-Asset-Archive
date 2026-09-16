import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app.routers import datasets


def test_dataset_delete_clears_versions_and_owned_relations(monkeypatch):
    database = SimpleNamespace(
        datasets=SimpleNamespace(find_one=AsyncMock(return_value={'id':'dataset'}), update_one=AsyncMock()),
        dataset_versions=SimpleNamespace(distinct=AsyncMock(return_value=['version']),delete_many=AsyncMock()),
        dataset_version_memberships=SimpleNamespace(delete_many=AsyncMock()),
        dataset_memberships=SimpleNamespace(delete_many=AsyncMock()),
        relations=SimpleNamespace(delete_many=AsyncMock(return_value=SimpleNamespace(deleted_count=3))),
    )
    audit=AsyncMock()
    monkeypatch.setattr(datasets,'db',database)
    monkeypatch.setattr(datasets,'record_audit',audit)
    asyncio.run(datasets.delete_dataset('dataset',SimpleNamespace(state=SimpleNamespace(request_id='test')),{'id':'user'}))
    database.dataset_versions.delete_many.assert_awaited_once_with({'dataset_id':'dataset'})
    database.dataset_memberships.delete_many.assert_awaited_once_with({'dataset_id':'dataset'})
    clauses=database.relations.delete_many.call_args.args[0]['$or']
    assert {'provenance.dataset_id':'dataset'} in clauses
    assert {'target_id':{'$in':['dataset','version']}} in clauses
    assert {'source_id':{'$in':['dataset','version']}} in clauses
    database.dataset_version_memberships.delete_many.assert_awaited_once_with({'$or':[{'dataset_id':'dataset'},{'version_id':{'$in':['version']}}]})
    assert audit.call_args.kwargs['changes']=={'versions_deleted':1,'relations_deleted':3}
