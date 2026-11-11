import { describe, expect, it } from 'vitest'
import { formatValidationErrors } from './validationErrors'

describe('API 表单校验提示', () => {
  it('把字段格式和长度错误转换为中文', () => {
    expect(formatValidationErrors([
      { loc:['body','username'], type:'string_pattern_mismatch', msg:'String should match pattern' },
      { loc:['body','remark'], type:'string_too_long', ctx:{max_length:200}, msg:'String should have at most 200 characters' },
    ])).toBe('用户名格式不正确；备注不能超过 200 个字符')
  })

  it('保留服务端已有的中文业务校验信息', () => {
    expect(formatValidationErrors([
      { loc:['body','projects'], type:'value_error', msg:'Value error, 所属项目不能为空或重复' },
    ])).toBe('所属项目不能为空或重复')
  })
})
