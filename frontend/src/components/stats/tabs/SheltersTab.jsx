import { useMemo } from 'react';
import ChartCard from '../ChartCard';
import StackedBar from '../StackedBar';
import InfoTip from '../../common/InfoTip';
import { crossTab, medicalByShelter } from '../../../utils/statsAgg';
import { MEDICAL_COLORS, COMPOSITION_PALETTE } from '../palette';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from 'recharts';

// Custom 100% stacked horizontal bar for the medical-compliance small-multiples.
// Recharts' built-in stacks don't normalize to 100%, so we pre-normalize here.
function MedicalBar({ rows }) {
  const data = rows.map((r) => {
    const total = r.yes + r.no + r.unknown;
    if (total === 0) return { shelter: r.shelter, yes: 0, no: 0, unknown: 0 };
    return {
      shelter: r.shelter,
      yes: (r.yes / total) * 100,
      no: (r.no / total) * 100,
      unknown: (r.unknown / total) * 100,
    };
  });
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eee5d7" horizontal={false} />
        <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: '#5c4a38' }} unit="%" />
        <YAxis type="category" dataKey="shelter" width={100} tick={{ fontSize: 10, fill: '#3c2a21' }} />
        <Tooltip formatter={(v) => `${v.toFixed(1)}%`} />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
        <Bar dataKey="yes" stackId="a" fill={MEDICAL_COLORS.yes} name="Yes" />
        <Bar dataKey="no" stackId="a" fill={MEDICAL_COLORS.no} name="No" />
        <Bar dataKey="unknown" stackId="a" fill={MEDICAL_COLORS.unknown} name="Unknown" />
      </BarChart>
    </ResponsiveContainer>
  );
}

function SheltersTab({ dogs }) {
  const sizeShelter = useMemo(
    () => crossTab(dogs, 'source_site', 'size', { colResolve: true }),
    [dogs],
  );
  const genderShelter = useMemo(
    () => crossTab(dogs, 'source_site', 'gender', { colResolve: true }),
    [dogs],
  );
  // age_category is already resolved server-side from age_en ?? age_from_desc.
  const ageShelter = useMemo(() => crossTab(dogs, 'source_site', 'age_category'), [dogs]);

  const microchip = useMemo(() => medicalByShelter(dogs, 'microchip'), [dogs]);
  const vaccine = useMemo(() => medicalByShelter(dogs, 'vaccine'), [dogs]);
  const sterilization = useMemo(() => medicalByShelter(dogs, 'sterilization'), [dogs]);
  const deworming = useMemo(() => medicalByShelter(dogs, 'deworming'), [dogs]);

  return (
    <div>
      <h4 className="stats-section-heading">Composition by shelter</h4>
      <div className="chart-grid chart-grid-3">
        <ChartCard
          title="Size mix per shelter"
          tip="Share of each size category at every shelter."
          tipId="shelters-size-tip"
        >
          <StackedBar data={sizeShelter.data} keys={sizeShelter.keys} percent palette={COMPOSITION_PALETTE} />
        </ChartCard>
        <ChartCard
          title="Gender mix per shelter"
          tip="Share of male versus female at every shelter."
          tipId="shelters-gender-tip"
        >
          <StackedBar data={genderShelter.data} keys={genderShelter.keys} percent palette={COMPOSITION_PALETTE} />
        </ChartCard>
        <ChartCard
          title="Age mix per shelter"
          tip="Share of each age category (puppy / young / adult / senior) at every shelter."
          tipId="shelters-age-tip"
        >
          <StackedBar data={ageShelter.data} keys={ageShelter.keys} percent palette={COMPOSITION_PALETTE} />
        </ChartCard>
      </div>

      <h4 className="stats-section-heading">
        Medical compliance per shelter
        <InfoTip id="shelters-medical-tip">
          "Unknown" means the shelter didn't expose that field and the LLM couldn't extract it from the description.
        </InfoTip>
      </h4>
      <div className="chart-grid chart-grid-4">
        <ChartCard title="Microchip" height={260}>
          <MedicalBar rows={microchip} />
        </ChartCard>
        <ChartCard title="Vaccine" height={260}>
          <MedicalBar rows={vaccine} />
        </ChartCard>
        <ChartCard title="Sterilization" height={260}>
          <MedicalBar rows={sterilization} />
        </ChartCard>
        <ChartCard title="Deworming" height={260}>
          <MedicalBar rows={deworming} />
        </ChartCard>
      </div>
    </div>
  );
}

export default SheltersTab;
