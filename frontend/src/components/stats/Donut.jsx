import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, Legend } from 'recharts';
import { colorFor } from './palette';

// Neutral grey for the "Unknown" / "Other" slices so they read visually
// distinct from the proper buckets.
const NEUTRAL_SLICE = '#cdbfae';
const NEUTRAL_NAMES = new Set(['Unknown', 'Other']);

function Donut({ data, dataKey = 'value', nameKey = 'name', innerRadius = '55%', outerRadius = '80%', showLegend = true }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          dataKey={dataKey}
          nameKey={nameKey}
          innerRadius={innerRadius}
          outerRadius={outerRadius}
          paddingAngle={1}
          stroke="#fff"
          strokeWidth={2}
        >
          {data.map((d, i) => (
            <Cell key={i} fill={NEUTRAL_NAMES.has(d[nameKey]) ? NEUTRAL_SLICE : colorFor(i)} />
          ))}
        </Pie>
        <Tooltip />
        {showLegend && <Legend verticalAlign="bottom" iconType="circle" />}
      </PieChart>
    </ResponsiveContainer>
  );
}

export default Donut;
