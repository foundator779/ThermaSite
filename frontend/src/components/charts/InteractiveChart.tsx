import {
  Bar,
  Brush,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ChartDefinition } from '../../types/run'

export function InteractiveChart({ definition, large = false }: { definition: ChartDefinition; large?: boolean }) {
  const axisFontSize = large ? 13 : 10
  const margin = large
    ? { top: 16, right: 30, bottom: definition.data.length > 8 ? 30 : 12, left: 16 }
    : { top: 8, right: 8, bottom: 0, left: -24 }
  const tooltipStyle = { border: '1px solid #dce7e1', borderRadius: 10, boxShadow: '0 10px 28px rgba(18,49,37,.12)', fontSize: 12 }

  if (definition.kind === 'scatter') {
    return <div className={`interactive-chart${large ? ' interactive-chart--large' : ''}`} data-chart-kind="scatter">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={margin}>
          <CartesianGrid stroke="#e7efea" strokeDasharray="3 3" />
          <XAxis type="number" dataKey={definition.x_key} name={definition.x_label} fontSize={axisFontSize} tickLine={false} axisLine={{ stroke: '#cad8d1' }} />
          <YAxis type="number" dataKey={definition.y_key} name={definition.y_label} unit={definition.unit ? ` ${definition.unit}` : undefined} fontSize={axisFontSize} tickLine={false} axisLine={{ stroke: '#cad8d1' }} width={large ? 72 : 52} />
          <Tooltip cursor={{ strokeDasharray: '3 3' }} contentStyle={tooltipStyle} />
          {large && <Legend />}
          <Scatter name={definition.series[0]?.label || definition.y_label} data={definition.data} fill={definition.series[0]?.color || '#2c8265'} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  }

  return <div className={`interactive-chart${large ? ' interactive-chart--large' : ''}`} data-chart-kind={definition.kind}>
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={definition.data} margin={margin}>
        <CartesianGrid vertical={false} stroke="#e7efea" />
        <XAxis dataKey={definition.x_key} fontSize={axisFontSize} tickLine={false} axisLine={{ stroke: '#cad8d1' }} minTickGap={18} />
        <YAxis fontSize={axisFontSize} tickLine={false} axisLine={false} width={large ? 64 : 44} />
        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(226,239,232,.45)' }} />
        {large && <Legend verticalAlign="top" height={34} />}
        {definition.series.map((series) => series.kind === 'bar' || definition.kind === 'bar'
          ? <Bar key={series.key} dataKey={series.key} name={series.label} fill={series.color} unit={definition.unit ? ` ${definition.unit}` : undefined} radius={[5, 5, 1, 1]} maxBarSize={large ? 54 : 36} isAnimationActive={false} />
          : <Line key={series.key} type="monotone" dataKey={series.key} name={series.label} stroke={series.color} unit={definition.unit ? ` ${definition.unit}` : undefined} strokeWidth={series.label.toLowerCase().includes('trend') ? 2 : 2.5} dot={large ? { r: 3 } : false} activeDot={{ r: 5 }} connectNulls isAnimationActive={false} />)}
        {large && definition.data.length > 8 && <Brush dataKey={definition.x_key} height={24} stroke="#5b927c" travellerWidth={8} />}
      </ComposedChart>
    </ResponsiveContainer>
  </div>
}
