import InfoTip from '../common/InfoTip';

// Wraps every chart so titles, captions, and the "single-shelter" pill
// render consistently. Pass `shelterPill` to surface a "Source: <shelter>"
// badge in the top-right (used inside Activity & Tenure sections).
// Pass `tip` to render a small info icon next to the title with hover text
// instead of (or alongside) the visible `subtitle` line.
function ChartCard({ title, subtitle, tip, tipId, shelterPill, height = 320, children, className = '' }) {
  const hasHead = title || subtitle || tip || shelterPill;
  return (
    <div className={`chart-card ${className}`}>
      {hasHead && (
        <div className="chart-card-head">
          <div className="chart-card-titles">
            {(title || tip) && (
              <div className="chart-card-title">
                {title}
                {tip && <InfoTip id={tipId || `chart-${title || 'card'}`}>{tip}</InfoTip>}
              </div>
            )}
            {subtitle && <div className="chart-card-subtitle">{subtitle}</div>}
          </div>
          {shelterPill && (
            <div className="chart-card-pill" title="This chart only reflects data from this shelter">
              Source: {shelterPill}
            </div>
          )}
        </div>
      )}
      <div className="chart-card-body" style={{ height }}>
        {children}
      </div>
    </div>
  );
}

export default ChartCard;
