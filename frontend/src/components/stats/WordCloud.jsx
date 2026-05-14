import { useEffect, useRef, useState } from 'react';
import D3Cloud from 'react-d3-cloud';
import { COMPOSITION_PALETTE } from './palette';

// Word cloud built on react-d3-cloud. The library takes pixel dimensions
// (no ResponsiveContainer), so we wrap it in a div whose width is measured
// via ResizeObserver and re-fed on resize. Height comes from the parent
// ChartCard's inline `height` (the wrapper div fills it via CSS).
function WordCloud({ data, height = 480 }) {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width;
      if (w && w !== width) setWidth(Math.floor(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Scale fonts as a share of the canvas height so the cloud actually fills
  // its card. Floor is generous (≈10% of card height) so even the smallest
  // words don't cluster at the centre; ceiling lets the most-frequent name
  // dominate. sqrt easing keeps low-count words from collapsing to the floor.
  const minFont = Math.max(22, Math.round(height * 0.11));
  const maxFont = Math.max(72, Math.round(height * 0.36));

  const maxValue = Math.max(1, ...data.map((d) => d.value));
  const minValue = Math.min(...data.map((d) => d.value));
  const fontSize = (word) => {
    if (maxValue === minValue) return (minFont + maxFont) / 2;
    const t = Math.sqrt((word.value - minValue) / (maxValue - minValue));
    return minFont + t * (maxFont - minFont);
  };

  // Convert { name, value } → { text, value } shape the lib expects.
  const wcData = data.map((d) => ({ text: d.name, value: d.value }));

  // Pick a deterministic colour per word from the composition palette so
  // colours are stable across renders.
  const fill = (_d, i) => COMPOSITION_PALETTE[i % COMPOSITION_PALETTE.length];

  return (
    <div ref={ref} style={{ width: '100%', height }}>
      {width > 0 && (
        <D3Cloud
          data={wcData}
          width={width}
          height={height}
          font="Fredoka, Nunito Sans, sans-serif"
          fontWeight={600}
          fontSize={fontSize}
          rotate={0}
          padding={6}
          fill={fill}
        />
      )}
    </div>
  );
}

export default WordCloud;
