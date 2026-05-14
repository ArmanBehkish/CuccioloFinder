import InfoTip from '../common/InfoTip';

function KpiCard({ value, label, tip, tipId, accent = false }) {
  return (
    <div className={`kpi-card${accent ? ' kpi-card-accent' : ''}`}>
      <div className="kpi-card-value">{value}</div>
      <div className="kpi-card-label">
        {label}
        {tip && <InfoTip id={tipId || `kpi-${label}`}>{tip}</InfoTip>}
      </div>
    </div>
  );
}

export default KpiCard;
