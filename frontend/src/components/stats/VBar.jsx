import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, LabelList } from 'recharts';
import { colorFor } from './palette';

// Vertical bar chart for ordered categories (age, week, etc.).
// Pass `rotateLabels` for dense category lists (e.g. good_with / bad_with)
// so x-axis labels don't overlap.
function VBar({ data, dataKey = 'count', nameKey = 'name', color, showLabel = false, rotateLabels = false }) {
  const xAxisProps = rotateLabels
    ? {
        angle: -35,
        textAnchor: 'end',
        interval: 0,
        height: 70,
      }
    : {};
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={data}
        margin={{ top: 16, right: 16, left: 0, bottom: rotateLabels ? 24 : 8 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#eee5d7" vertical={false} />
        <XAxis
          dataKey={nameKey}
          tick={{ fontSize: 11, fill: '#3c2a21' }}
          {...xAxisProps}
        />
        <YAxis tick={{ fontSize: 11, fill: '#5c4a38' }} allowDecimals={false} />
        <Tooltip cursor={{ fill: 'rgba(184, 134, 78, 0.08)' }} />
        <Bar dataKey={dataKey} fill={color || colorFor(0)} radius={[4, 4, 0, 0]}>
          {showLabel && <LabelList dataKey={dataKey} position="top" style={{ fontSize: 11, fill: '#3c2a21' }} />}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export default VBar;
