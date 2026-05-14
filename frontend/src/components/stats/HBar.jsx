import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { colorFor } from './palette';

// Horizontal bar chart driven by recharts' `layout="vertical"`. Categories
// on the Y axis, values on the X axis.
function HBar({ data, dataKey = 'value', nameKey = 'name', color, yAxisWidth = 130, showGrid = true }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 24, left: 8, bottom: 8 }}>
        {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#eee5d7" horizontal={false} />}
        <XAxis type="number" tick={{ fontSize: 11, fill: '#5c4a38' }} />
        <YAxis
          type="category"
          dataKey={nameKey}
          width={yAxisWidth}
          tick={{ fontSize: 11, fill: '#3c2a21' }}
        />
        <Tooltip cursor={{ fill: 'rgba(184, 134, 78, 0.08)' }} />
        <Bar dataKey={dataKey} fill={color || colorFor(0)} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default HBar;
