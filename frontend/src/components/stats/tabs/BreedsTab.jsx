import { useMemo } from 'react';
import ChartCard from '../ChartCard';
import HBar from '../HBar';
import Donut from '../Donut';
import WordCloud from '../WordCloud';
import InfoTip from '../../common/InfoTip';
import { countByResolved, topNWithOther, pureVsMixed } from '../../../utils/statsAgg';

function BreedsTab({ dogs }) {
  const allBreeds = useMemo(() => countByResolved(dogs, 'breed'), [dogs]);
  const topBreeds = useMemo(
    // recharts horizontal bar reads top-to-bottom; reverse so highest sits on top
    () => topNWithOther(allBreeds, 15).reverse(),
    [allBreeds],
  );

  const pureMixed = useMemo(() => pureVsMixed(dogs), [dogs]);

  const names = useMemo(() => {
    const counts = {};
    for (const r of dogs) {
      const n = (r.name || '').trim();
      if (!n) continue;
      counts[n] = (counts[n] || 0) + 1;
    }
    return Object.entries(counts)
      .map(([name, value]) => ({ name, value }))
      .filter((d) => d.value > 1) // single-occurrence names are noise here
      .sort((a, b) => b.value - a.value);
  }, [dogs]);

  // Word-cloud cap — d3-cloud lays words out by font size; too many smaller
  // words just become illegible. 40 is a balance: enough variety, still
  // readable at common card widths.
  const topNames = useMemo(() => names.slice(0, 40), [names]);

  return (
    <div>
      <h4 className="stats-section-heading">
        Claimed breeds
        <InfoTip id="breeds-claimed-section-tip">
          "Claimed breed" is what the shelter wrote in the structured breed field (translated to English).
          It's free-form and may contain "Mixed", "Labrador mix", etc.
        </InfoTip>
      </h4>
      <div className="chart-grid chart-grid-2">
        <ChartCard
          title="Top 15 most common claimed breeds"
          tip="The 15 most-claimed breeds across all shelters; the rest are grouped together as 'Other'."
          tipId="breeds-top15-tip"
          height={420}
        >
          <HBar data={topBreeds} yAxisWidth={170} />
        </ChartCard>
        <ChartCard
          title="Pure vs mixed (claimed)"
          tip='Pure vs mixed is detected by keyword matching on the claimed breed string (e.g. "mix", "cross", "meticcio").'
          tipId="breeds-pure-mixed-tip"
          height={420}
        >
          <Donut data={pureMixed} innerRadius="50%" outerRadius="75%" />
        </ChartCard>
      </div>

      <h4 className="stats-section-heading">
        Common Names
        <InfoTip id="breeds-names-section-tip">
          The larger the name, the more dogs in the dataset share it.
        </InfoTip>
      </h4>
      <ChartCard height={300}>
        <WordCloud data={topNames} height={300} />
      </ChartCard>
    </div>
  );
}

export default BreedsTab;
