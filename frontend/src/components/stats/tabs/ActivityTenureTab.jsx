import { useMemo } from 'react';
import ChartCard from '../ChartCard';
import VBar from '../VBar';
import LineSeries from '../LineSeries';
import CalendarHeatmap from '../CalendarHeatmap';
import InfoTip from '../../common/InfoTip';
import {
  dailyCounts, cumulativeByMonth,
  waitHistogram, averageWaitBy,
} from '../../../utils/statsAgg';

// Builds the short scope note shown in each section's title tooltip.
function shelterScopeMessage(sources, fieldDescription) {
  if (sources.length === 0) return '';
  return `${fieldDescription} ${sources.join(', ')}.`;
}

// dateSupport comes from /api/enums.date_support — auto-discovered from the
// DB so adding a new spider that emits post_date will widen the banner.
function ActivityTenureTab({ dogs, dateSupport }) {
  const postSources = dateSupport?.post_date || [];
  const shelterSinceSources = dateSupport?.shelter_since || [];

  const postRows = useMemo(
    () => dogs.filter((d) => postSources.includes(d.source_site)),
    [dogs, postSources],
  );
  const shelterSinceRows = useMemo(
    () => dogs.filter((d) => shelterSinceSources.includes(d.source_site)),
    [dogs, shelterSinceSources],
  );

  const daily = useMemo(() => dailyCounts(postRows, 'post_date'), [postRows]);
  const cumulative = useMemo(() => cumulativeByMonth(postRows, 'post_date'), [postRows]);

  const waitHist = useMemo(() => waitHistogram(shelterSinceRows, 'shelter_since'), [shelterSinceRows]);
  const waitByAge = useMemo(
    () => averageWaitBy(shelterSinceRows, 'age_category', 'shelter_since'),
    [shelterSinceRows],
  );
  const waitByGender = useMemo(
    () => averageWaitBy(shelterSinceRows, 'gender', 'shelter_since', { resolved: true }),
    [shelterSinceRows],
  );

  const pillPost = postSources.length === 1 ? postSources[0] : null;
  const pillShelter = shelterSinceSources.length === 1 ? shelterSinceSources[0] : null;

  return (
    <div>
      {/* New listings (post_date) */}
      {postSources.length > 0 ? (
        <section className="single-shelter-section">
          <h4 className="single-shelter-section-title">
            New listings over time
            <InfoTip id="activity-post-scope-tip">
              {shelterScopeMessage(postSources, 'Listing post dates are only reported by')}
            </InfoTip>
          </h4>
          <div className="chart-grid chart-grid-2">
            <ChartCard
              title="Dogs added by date"
              tip="Each square is a day; the darker it is, the more dogs were first listed that day."
              tipId="activity-calendar-tip"
              shelterPill={pillPost}
              height={300}
            >
              <CalendarHeatmap data={daily} valueLabel="new listings" />
            </ChartCard>
            <ChartCard
              title="Cumulative active listings by month"
              tip="Running total of all listings posted up to and including that month."
              tipId="activity-cumulative-tip"
              shelterPill={pillPost}
              height={300}
            >
              <LineSeries data={cumulative} xKey="month" yKey="cumulative" />
            </ChartCard>
          </div>
        </section>
      ) : (
        <div className="stats-note">No shelters in the dataset currently expose listing post dates.</div>
      )}

      {/* Wait time (shelter_since) */}
      {shelterSinceSources.length > 0 ? (
        <section className="single-shelter-section">
          <h4 className="single-shelter-section-title">
            Time in shelter
            <InfoTip id="activity-shelter-since-scope-tip">
              {shelterScopeMessage(shelterSinceSources, '"In shelter since" dates are only reported by')}
            </InfoTip>
          </h4>
          <div className="chart-grid chart-grid-2">
            <ChartCard
              title="How long current dogs have been waiting"
              tip="Number of currently-listed dogs by how long they've been in the shelter, bucketed in days."
              tipId="activity-wait-hist-tip"
              shelterPill={pillShelter}
              height={300}
            >
              <VBar data={waitHist} dataKey="count" nameKey="name" color="#e07a5f" showLabel />
            </ChartCard>
            <ChartCard
              title="Average wait by age category"
              tip="Average number of days currently-listed dogs have been in the shelter, grouped by age category."
              tipId="activity-wait-age-tip"
              shelterPill={pillShelter}
              height={300}
            >
              <VBar data={waitByAge} dataKey="avgDays" nameKey="name" color="#81a263" showLabel />
            </ChartCard>
          </div>
          <div className="chart-grid chart-grid-2">
            <ChartCard
              title="Average wait by gender"
              tip="Average number of days currently-listed dogs have been in the shelter, grouped by gender."
              tipId="activity-wait-gender-tip"
              shelterPill={pillShelter}
              height={300}
            >
              <VBar data={waitByGender} dataKey="avgDays" nameKey="name" color="#4a6072" showLabel />
            </ChartCard>
          </div>
        </section>
      ) : (
        <div className="stats-note">No shelters in the dataset currently expose intake dates.</div>
      )}
    </div>
  );
}

export default ActivityTenureTab;
