import { ResponsiveHeatMap } from '@nivo/heatmap';

// Nivo heatmap wrapper. Data shape:
//   [{ id: rowLabel, data: [{ x: colLabel, y: value }, ...] }, ...]
//
// `labelThreshold` controls the cell value at which the label flips from
// dark text (on pale cells) to light text (on dark cells). Use the midpoint
// of the colour ramp — defaults to halfway between min and max.
function Heatmap({ data, valueLabel = 'Count', colorScheme = 'oranges', minValue, maxValue, labelThreshold }) {
  const lo = minValue ?? 0;
  const hi = maxValue ?? 100;
  const threshold = labelThreshold ?? (lo + hi) / 2;

  const labelColor = (cell) => {
    const v = cell?.data?.y;
    if (v == null) return '#3c2a21';
    return v > threshold ? '#ffffff' : '#1a1009';
  };

  return (
    <ResponsiveHeatMap
      data={data}
      margin={{ top: 16, right: 36, bottom: 60, left: 110 }}
      valueFormat=">-.0f"
      axisTop={null}
      axisRight={null}
      axisBottom={{
        tickSize: 5,
        tickPadding: 5,
        tickRotation: -25,
        legend: '',
        legendPosition: 'middle',
        legendOffset: 36,
      }}
      axisLeft={{
        tickSize: 5,
        tickPadding: 5,
      }}
      colors={{
        type: 'sequential',
        scheme: colorScheme,
        minValue,
        maxValue,
      }}
      emptyColor="#faf5ed"
      borderColor="#fff"
      borderWidth={1}
      borderRadius={3}
      labelTextColor={labelColor}
      theme={{
        labels: {
          text: {
            fontSize: 12,
            fontWeight: 700,
            fontFamily: "'Nunito Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
          },
        },
      }}
      animate={false}
      hoverTarget="cell"
      tooltip={({ cell }) => (
        <div style={{
          background: '#6b5840', color: '#fff', padding: '6px 10px',
          borderRadius: 4, fontSize: 12,
        }}>
          <div><strong>{cell.serieId}</strong> × <strong>{cell.data.x}</strong></div>
          <div>{valueLabel}: {cell.data.y}</div>
        </div>
      )}
    />
  );
}

export default Heatmap;
