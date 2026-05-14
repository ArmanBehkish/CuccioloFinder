import { useMemo } from 'react';
import ChartCard from '../ChartCard';
import StackedBar from '../StackedBar';
import Heatmap from '../Heatmap';
import InfoTip from '../../common/InfoTip';
import { COMPOSITION_PALETTE } from '../palette';
import {
  fieldCompleteness, completenessHeatmap, descriptionLengthByShelter,
} from '../../../utils/statsAgg';

// `resolved: true` means a dog counts as populated when either `_en` or
// `_from_desc` carries a value (matches the rest of the page's merge rule).
// Fields without that suffix pair are read directly.
const COMPLETENESS_FIELDS = [
  { key: 'gender', label: 'Gender', resolved: true },
  { key: 'age', label: 'Age', resolved: true },
  { key: 'size', label: 'Size', resolved: true },
  { key: 'breed', label: 'Breed', resolved: true },
  { key: 'fur', label: 'Fur', resolved: true },
  { key: 'weight', label: 'Weight', resolved: true },
  { key: 'microchip', label: 'Microchip', resolved: true },
  { key: 'vaccine', label: 'Vaccine', resolved: true },
  { key: 'sterilization', label: 'Sterilization', resolved: true },
  { key: 'deworming', label: 'Deworming', resolved: true },
  { key: 'good_with', label: 'Good with', resolved: true },
  { key: 'bad_with', label: 'Bad with', resolved: true },
  { key: 'description_en', label: 'Description' },
  { key: 'post_date', label: 'Post date' },
  { key: 'shelter_since', label: 'Shelter since' },
];

function DataQualityTab({ dogs }) {
  const completeness = useMemo(() => fieldCompleteness(dogs, COMPLETENESS_FIELDS), [dogs]);

  // Reshape to recharts-stacked form: each row is a field, segments are populated/missing %.
  // Round populated to the nearest integer and derive missing from it so the
  // two always sum to 100 in the tooltip.
  const completenessRows = useMemo(
    () => completeness
      .slice()
      .sort((a, b) => a.pct - b.pct)
      .map((c) => {
        const populated = Math.round(c.pct);
        return {
          row: c.label,
          populated,
          missing: 100 - populated,
        };
      }),
    [completeness],
  );

  const heatmap = useMemo(
    () => completenessHeatmap(dogs, COMPLETENESS_FIELDS),
    [dogs],
  );

  const descByShelter = useMemo(() => descriptionLengthByShelter(dogs), [dogs]);

  return (
    <div>
      <h4 className="stats-section-heading">
        Field completeness
        <InfoTip id="quality-completeness-section-tip">
          Share of dogs with a populated value for each field. Empty arrays / empty strings count as missing.
        </InfoTip>
      </h4>
      <ChartCard
        title="Populated vs missing per field"
        tip="Sorted from least to most populated."
        tipId="quality-completeness-chart-tip"
        height={Math.max(380, completenessRows.length * 26)}
      >
        <StackedBar
          data={completenessRows}
          keys={['populated', 'missing']}
          layout="horizontal"
          percent={false}
          palette={['#81a263', '#cdbfae']}
        />
      </ChartCard>

      <h4 className="stats-section-heading">Completeness heatmap</h4>
      <ChartCard
        title="Per shelter × per field"
        tip="Each cell is the % of dogs at that shelter with that field populated. Pale = lots of gaps, deep green = mostly complete."
        tipId="quality-heatmap-chart-tip"
        height={Math.max(360, heatmap.shelters.length * 50)}
      >
        <Heatmap data={heatmap.matrix} valueLabel="% populated" colorScheme="greens" minValue={0} maxValue={100} />
      </ChartCard>

      <h4 className="stats-section-heading">
        Description length
        <InfoTip id="quality-desc-section-tip">
          Distribution of descriptions' length in characters.
        </InfoTip>
      </h4>
      <ChartCard
        title="Distribution by shelter"
        tip="Number of dogs in each description-length bucket, grouped by shelter."
        tipId="quality-desc-chart-tip"
        height={320}
      >
        <StackedBar
          data={descByShelter.data}
          keys={descByShelter.keys}
          palette={COMPOSITION_PALETTE}
          grouped
        />
      </ChartCard>
    </div>
  );
}

export default DataQualityTab;
