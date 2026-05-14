import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from 'recharts';
import { colorFor } from './palette';

// Stacked bar driven by crossTab() output:
//   data: [{ row: 'canileoasi', small: 4, medium: 12 }, ...]
//   keys: ['small', 'medium', 'large']
// `palette` (optional): explicit array of hex colours. Falls back to the
// generic cycling palette when omitted.
// `grouped` (optional): render bars side-by-side per row instead of stacked.
function StackedBar({ data, keys, rowKey = 'row', layout = 'vertical', percent = false, palette, grouped = false }) {
  const colorAt = (i) => (palette ? palette[i % palette.length] : colorFor(i));
  // percent=true -> normalize each row to 1
  let chartData = data;
  if (percent) {
    chartData = data.map((d) => {
      const total = keys.reduce((s, k) => s + (d[k] || 0), 0);
      const out = { [rowKey]: d[rowKey] };
      for (const k of keys) out[k] = total === 0 ? 0 : ((d[k] || 0) / total) * 100;
      return out;
    });
  }

  const isHorizontal = layout === 'horizontal';

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={chartData}
        layout={isHorizontal ? 'vertical' : 'horizontal'}
        margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#eee5d7" />
        {isHorizontal ? (
          <>
            <XAxis type="number" domain={percent ? [0, 100] : undefined} tick={{ fontSize: 11, fill: '#5c4a38' }} />
            <YAxis type="category" dataKey={rowKey} width={110} tick={{ fontSize: 11, fill: '#3c2a21' }} />
          </>
        ) : (
          <>
            <XAxis dataKey={rowKey} tick={{ fontSize: 11, fill: '#3c2a21' }} />
            <YAxis domain={percent ? [0, 100] : undefined} tick={{ fontSize: 11, fill: '#5c4a38' }} allowDecimals={false} />
          </>
        )}
        <Tooltip
          formatter={(v) => (percent ? `${v.toFixed(1)}%` : v)}
          cursor={{ fill: 'rgba(184, 134, 78, 0.08)' }}
        />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
        {keys.map((k, i) => (
          <Bar
            key={k}
            dataKey={k}
            {...(grouped ? {} : { stackId: 'a' })}
            fill={colorAt(i)}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export default StackedBar;
