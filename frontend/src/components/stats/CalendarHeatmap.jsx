import { ResponsiveCalendar } from '@nivo/calendar';

// Calendar heatmap (one tile per day) for daily aggregates. Expects
// `data` as [{ day: 'YYYY-MM-DD', value }] — the shape nivo wants natively.
// Derives `from` / `to` from the data so the calendar always frames the
// populated range without callers having to know the date span.
function CalendarHeatmap({ data, valueLabel = 'count', emptyColor = '#f5ecdc' }) {
  if (!data.length) return null;
  const from = data[0].day;
  const to = data[data.length - 1].day;

  return (
    <ResponsiveCalendar
      data={data}
      from={from}
      to={to}
      emptyColor={emptyColor}
      colors={['#f3dec3', '#e8b97a', '#d97a5a', '#b8864e', '#6b4226']}
      margin={{ top: 24, right: 24, bottom: 24, left: 24 }}
      yearSpacing={36}
      yearLegendOffset={10}
      monthBorderColor="transparent"
      monthLegendOffset={8}
      monthLegendPosition="before"
      dayBorderWidth={1}
      dayBorderColor="#faf7f2"
      theme={{
        labels: { text: { fontSize: 11, fill: '#5c4a38' } },
      }}
      tooltip={({ day, value, color }) => {
        if (value === undefined) return null;
        return (
          <div style={{
            background: '#6b5840', color: '#fff', padding: '6px 10px',
            borderRadius: 4, fontSize: 12,
          }}>
            <strong>{day}</strong> — {value} {valueLabel}
            <span style={{
              display: 'inline-block', width: 8, height: 8,
              background: color, marginLeft: 6, borderRadius: 2,
            }} />
          </div>
        );
      }}
    />
  );
}

export default CalendarHeatmap;
