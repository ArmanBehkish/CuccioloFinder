import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Area, AreaChart } from 'recharts';
import { colorFor } from './palette';

function LineSeries({ data, xKey, yKey = 'count', color, area = false }) {
  const fill = color || colorFor(0);
  const stroke = color || colorFor(0);

  if (area) {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 16, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eee5d7" vertical={false} />
          <XAxis dataKey={xKey} tick={{ fontSize: 10, fill: '#5c4a38' }} />
          <YAxis tick={{ fontSize: 11, fill: '#5c4a38' }} allowDecimals={false} />
          <Tooltip />
          <Area type="monotone" dataKey={yKey} stroke={stroke} fill={fill} fillOpacity={0.2} strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 16, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eee5d7" vertical={false} />
        <XAxis dataKey={xKey} tick={{ fontSize: 10, fill: '#5c4a38' }} />
        <YAxis tick={{ fontSize: 11, fill: '#5c4a38' }} allowDecimals={false} />
        <Tooltip />
        <Line type="monotone" dataKey={yKey} stroke={stroke} strokeWidth={2} dot={{ r: 3 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export default LineSeries;
