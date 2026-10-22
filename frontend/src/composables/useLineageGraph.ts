import { computed, type Ref } from 'vue'

type LineageState = {
  edges: Ref<any[]>
  nodes: Ref<any[]>
  root: Ref<any>
  typeFilter: Ref<string>
  expanded: Ref<string>
  typeLabels: Record<string, string>
}

export function useLineageGraph(state: LineageState) {
  const filteredLineageEdges = computed(() => state.edges.value.filter((edge: any) => {
    if (!state.typeFilter.value) return true
    if (state.typeFilter.value === 'dataset_version') return edge.relation_type === 'trained_on' && edge.target_type === 'dataset_version'
    return edge.target_type === state.typeFilter.value && (edge.derived || edge.relation_type === 'annotates')
  }))
  const lineageGroups = computed(() => Object.entries(filteredLineageEdges.value.reduce((groups: Record<string, any[]>, edge: any) => {
    const key = edge.target_type || 'asset'
    ;(groups[key] ||= []).push(edge)
    return groups
  }, {})))
  const lineageNodeMap = computed(() => new Map(state.nodes.value.map((item: any) => [String(item.id), item])))
  const lineageRootEdges = computed(() => {
    const rootId = String(state.root.value?.id || '')
    return state.edges.value.filter((edge: any) => String(edge.source_id) === rootId && edge.relation_type === 'trained_on')
  })
  const lineageVersionIds = computed(() => new Set(state.edges.value.filter((edge: any) =>
    String(edge.source_id) === String(state.root.value?.id) && edge.relation_type === 'trained_on' && edge.target_type === 'dataset_version',
  ).map((edge: any) => String(edge.target_id))))
  const lineageMemberEdges = computed(() => filteredLineageEdges.value.filter((edge: any) =>
    edge.derived && lineageVersionIds.value.has(String(edge.source_id)),
  ))
  const lineageAssetGroups = computed(() => ([
    { key: 'image', label: '图片文件' }, { key: 'annotation', label: '标注文件' },
    { key: 'video', label: '视频文件' }, { key: 'archive', label: '压缩文件' },
    { key: 'other', label: '其他文件' },
  ].filter(group => !state.typeFilter.value || state.typeFilter.value === group.key).map(group => {
    const items = new Map<string, any>()
    for (const edge of lineageMemberEdges.value.filter((item: any) => item.target_type === group.key)) {
      const id = String(edge.target_id)
      if (!items.has(id)) items.set(id, { id, name: edge.target, type: group.key, edge, sources: [] })
      const node = lineageNodeMap.value.get(String(edge.source_id)) || {}
      items.get(id).sources.push({
        id: String(edge.source_id), name: node.dataset_name || edge.source,
        version: node.version || '未知版本', edgeId: edge.id,
      })
    }
    return { ...group, items: [...items.values()] }
  })).filter(group => group.items.length > 0))
  const lineageDatasets = computed(() => state.typeFilter.value && state.typeFilter.value !== 'dataset_version' ? [] :
    lineageRootEdges.value.filter((edge: any) => ['dataset', 'dataset_version', 'snapshot', 'manual'].includes(edge.target_type))
      .map((edge: any) => ({
        id: String(edge.target_id), name: edge.target, type: edge.target_type,
        typeLabel: edge.targetType || state.typeLabels[edge.target_type] || '数据集',
        relation: edge.relation, edge, node: lineageNodeMap.value.get(String(edge.target_id)) || {},
      })))
  const lineageDisplayedNodeCount = computed(() => 1 + lineageAssetGroups.value.reduce((count, group) => count + group.items.length, 0) + lineageDatasets.value.length)
  const lineageDisplayedRelationCount = computed(() => new Set([
    ...lineageDatasets.value.map((item: any) => item.edge.id),
    ...lineageAssetGroups.value.flatMap(group => group.items.flatMap((item: any) => item.sources.map((source: any) => source.edgeId))),
  ]).size)

  function toggleLineageGroup(group: string) {
    state.expanded.value = state.expanded.value === group ? '' : group
  }

  return {
    filteredLineageEdges, lineageGroups, lineageAssetGroups, lineageDatasets,
    lineageDisplayedNodeCount, lineageDisplayedRelationCount, toggleLineageGroup,
  }
}
