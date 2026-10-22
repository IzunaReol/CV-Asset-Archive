import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { useLineageGraph } from './useLineageGraph'

describe('模型溯源图模块', () => {
  it('按版本合并同一素材来源，并按类型筛选', () => {
    const typeFilter = ref('')
    const expanded = ref('')
    const graph = useLineageGraph({
      root: ref({ id: 'model' }),
      nodes: ref([
        { id: 'v1', dataset_name: '训练集', version: 'v1' },
        { id: 'v2', dataset_name: '训练集', version: 'v2' },
      ]),
      edges: ref([
        { id: 'r1', source_id: 'model', target_id: 'v1', relation_type: 'trained_on', target_type: 'dataset_version', target: '训练集 v1' },
        { id: 'r2', source_id: 'model', target_id: 'v2', relation_type: 'trained_on', target_type: 'dataset_version', target: '训练集 v2' },
        { id: 'e1', source_id: 'v1', target_id: 'image', target_type: 'image', target: '图片.jpg', derived: true },
        { id: 'e2', source_id: 'v2', target_id: 'image', target_type: 'image', target: '图片.jpg', derived: true },
      ]),
      typeFilter, expanded, typeLabels: { dataset_version: '数据集版本' },
    })

    expect(graph.lineageAssetGroups.value).toHaveLength(1)
    expect(graph.lineageAssetGroups.value[0].items[0].sources).toHaveLength(2)
    expect(graph.lineageDisplayedNodeCount.value).toBe(4)
    graph.toggleLineageGroup('image')
    expect(expanded.value).toBe('image')
    typeFilter.value = 'dataset_version'
    expect(graph.lineageAssetGroups.value).toHaveLength(0)
    expect(graph.lineageDatasets.value).toHaveLength(2)
  })
})
