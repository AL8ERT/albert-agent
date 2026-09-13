/**
 * 模型下拉选择器。
 */

import './ModelSelector.css'

type ModelSelectorProps = {
  models: string[]
  value: string
  disabled: boolean
  onChange: (model: string) => void
}

export function ModelSelector({
  models,
  value,
  disabled,
  onChange,
}: ModelSelectorProps) {
  return (
    <select
      className="model-selector"
      value={value}
      // 没有可用模型或正在回复时禁用切换
      disabled={disabled || models.length === 0}
      onChange={(event) => onChange(event.target.value)}
    >
      {models.length === 0 && <option value="">未配置模型</option>}
      {models.map((model) => (
        <option key={model} value={model}>
          {model}
        </option>
      ))}
    </select>
  )
}
