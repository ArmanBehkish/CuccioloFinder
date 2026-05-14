import { useMemo } from 'react';
import KpiCard from '../KpiCard';
import ChartCard from '../ChartCard';
import Donut from '../Donut';
import HBar from '../HBar';
import {
  countBy, countByResolved, uniqueCount, medicalSplit, recentCount,
} from '../../../utils/statsAgg';

function pct(rate) {
  if (rate === null || rate === undefined) return '—';
  return `${Math.round(rate * 100)}%`;
}

// Share over *all* dogs (including those with no recorded value).
// Different from medicalSplit().rate, which is share over yes+no only.
function pctOfTotal(yes, total) {
  if (total === 0) return null;
  return yes / total;
}

function OverviewTab({ dogs }) {
  const total = dogs.length;
  const shelters = useMemo(() => uniqueCount(dogs, 'source_site'), [dogs]);
  const newMonth = useMemo(() => recentCount(dogs, 'post_date', 30), [dogs]);

  const vacc = useMemo(() => medicalSplit(dogs, 'vaccine'), [dogs]);
  const ster = useMemo(() => medicalSplit(dogs, 'sterilization'), [dogs]);
  const chip = useMemo(() => medicalSplit(dogs, 'microchip'), [dogs]);

  // Donuts include an "Unknown" slice so each pie sums to all dogs.
  const opts = { includeUnknown: true };
  const genderData = useMemo(() => countByResolved(dogs, 'gender', opts), [dogs]);
  const sizeData = useMemo(() => countByResolved(dogs, 'size', opts), [dogs]);
  const ageData = useMemo(() => countBy(dogs, 'age_category', opts), [dogs]);
  const weightData = useMemo(() => countBy(dogs, 'weight_category', opts), [dogs]);
  const furData = useMemo(() => countByResolved(dogs, 'fur', opts), [dogs]);

  const perShelter = useMemo(
    () => countBy(dogs, 'source_site').sort((a, b) => b.value - a.value),
    [dogs],
  );

  return (
    <div>
      <div className="kpi-strip">
        <KpiCard value={total} label="Total dogs" accent />
        <KpiCard value={shelters} label="Shelters covered" accent />
        <KpiCard
          value={newMonth}
          label="New in last 30 days"
          tipId="kpi-new-30"
          tip="Only counts dogs from shelters that expose a listing post date. Other shelters' new dogs are not reflected here."
          accent
        />
        <KpiCard
          value={pct(pctOfTotal(vacc.yes, total))}
          label="Vaccinated"
          tipId="kpi-vacc"
          tip={`${vacc.yes} of ${total} dogs are recorded as vaccinated. The rest are either not vaccinated or have no value recorded.`}
          accent
        />
        <KpiCard
          value={pct(pctOfTotal(ster.yes, total))}
          label="Sterilized"
          tipId="kpi-ster"
          tip={`${ster.yes} of ${total} dogs are recorded as sterilized. The rest are either not sterilized or have no value recorded.`}
          accent
        />
        <KpiCard
          value={pct(pctOfTotal(chip.yes, total))}
          label="Microchipped"
          tipId="kpi-chip"
          tip={`${chip.yes} of ${total} dogs are recorded as microchipped. The rest are either not microchipped or have no value recorded.`}
          accent
        />
      </div>

      <h4 className="stats-section-heading">Population breakdown</h4>
      <div className="chart-grid chart-grid-3">
        <ChartCard title="Gender" height={280}>
          <Donut data={genderData} />
        </ChartCard>
        <ChartCard title="Size" height={280}>
          <Donut data={sizeData} />
        </ChartCard>
        <ChartCard title="Age" height={280}>
          <Donut data={ageData} />
        </ChartCard>
      </div>

      <div className="chart-grid chart-grid-3">
        <ChartCard title="Weight" height={280}>
          <Donut data={weightData} />
        </ChartCard>
        <ChartCard title="Fur" height={280}>
          <Donut data={furData} />
        </ChartCard>
        <ChartCard title="Dogs per shelter" height={280}>
          <HBar data={perShelter} yAxisWidth={110} />
        </ChartCard>
      </div>
    </div>
  );
}

export default OverviewTab;
