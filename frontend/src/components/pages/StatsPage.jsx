import { useState, useEffect } from 'react';
import Alert from 'react-bootstrap/Alert';
import { getWorkerStatus } from '../../api/dogs';
import { useStats } from '../../hooks/useStats';
import { useEnums } from '../../hooks/useEnums';
import StatsTabs from '../stats/StatsTabs';
import OverviewTab from '../stats/tabs/OverviewTab';
import SheltersTab from '../stats/tabs/SheltersTab';
import BreedsTab from '../stats/tabs/BreedsTab';
import CompatibilityTab from '../stats/tabs/CompatibilityTab';
import ActivityTenureTab from '../stats/tabs/ActivityTenureTab';
import DataQualityTab from '../stats/tabs/DataQualityTab';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorAlert from '../common/ErrorAlert';
import './StatsPage.css';

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'shelters', label: 'Shelters' },
  { key: 'breeds', label: 'Breeds & Names' },
  { key: 'compat', label: 'Compatibility' },
  { key: 'activity', label: 'Activity & Tenure' },
  { key: 'quality', label: 'Data Quality' },
];

function StatsPage() {
  const [workerBusy, setWorkerBusy] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');

  // Worker check first — when busy, /api/stats may be mid-rebuild.
  useEffect(() => {
    getWorkerStatus()
      .then((d) => setWorkerBusy(d.busy))
      .catch(() => setWorkerBusy(false));
  }, []);

  const { stats, loading: statsLoading, error: statsError } = useStats(workerBusy === false);
  const { enums } = useEnums(workerBusy === false);

  if (workerBusy === null) return <LoadingSpinner text="Checking server status..." />;

  if (workerBusy) {
    return (
      <div>
        <div className="page-header">
          <h2>Statistics</h2>
        </div>
        <Alert variant="warning">
          Data update in progress. Statistics will refresh once the worker finishes rebuilding the database.
        </Alert>
      </div>
    );
  }

  if (statsLoading) return <LoadingSpinner text="Loading statistics..." />;
  if (statsError) return <ErrorAlert message={`Failed to load stats: ${statsError}`} />;
  if (!stats || !stats.dogs) return <ErrorAlert message="No statistics available." />;

  const dogs = stats.dogs;

  return (
    <div>
      <div className="page-header">
        <h2>Statistics</h2>
        <p>Aggregated view over {stats.total} active {stats.total === 1 ? 'dog' : 'dogs'} across all shelters.</p>
      </div>

      <StatsTabs tabs={TABS} activeKey={activeTab} onChange={setActiveTab} />

      {activeTab === 'overview' && <OverviewTab dogs={dogs} />}
      {activeTab === 'shelters' && <SheltersTab dogs={dogs} />}
      {activeTab === 'breeds' && <BreedsTab dogs={dogs} />}
      {activeTab === 'compat' && <CompatibilityTab dogs={dogs} />}
      {activeTab === 'activity' && <ActivityTenureTab dogs={dogs} dateSupport={enums?.date_support} />}
      {activeTab === 'quality' && <DataQualityTab dogs={dogs} />}
    </div>
  );
}

export default StatsPage;
