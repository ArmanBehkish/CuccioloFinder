import { useMemo } from 'react';
import ChartCard from '../ChartCard';
import VBar from '../VBar';
import { countByMultiResolved } from '../../../utils/statsAgg';

function CompatibilityTab({ dogs }) {
  // Sort descending by frequency so the chart reads left → right.
  const goodWith = useMemo(
    () => countByMultiResolved(dogs, 'good_with'),
    [dogs],
  );
  const badWith = useMemo(
    () => countByMultiResolved(dogs, 'bad_with'),
    [dogs],
  );

  return (
    <div>
      <h4 className="stats-section-heading">Compatibility frequency</h4>
      <div className="chart-grid">
        <ChartCard
          title="Good with"
          tip="How many dogs are tagged as good with each group."
          tipId="compat-good-with-tip"
          height={360}
        >
          <VBar data={goodWith} dataKey="value" color="#4f8f78" rotateLabels />
        </ChartCard>
        <ChartCard
          title="Bad with"
          tip="How many dogs are tagged as not good with each group."
          tipId="compat-bad-with-tip"
          height={360}
        >
          <VBar data={badWith} dataKey="value" color="#d97a5a" rotateLabels />
        </ChartCard>
      </div>
    </div>
  );
}

export default CompatibilityTab;
