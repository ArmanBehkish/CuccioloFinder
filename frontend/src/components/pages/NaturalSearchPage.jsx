import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Row from 'react-bootstrap/Row';
import Col from 'react-bootstrap/Col';
import Form from 'react-bootstrap/Form';
import Button from 'react-bootstrap/Button';
import Badge from 'react-bootstrap/Badge';
import Alert from 'react-bootstrap/Alert';
import DogCardGrid from '../common/DogCardGrid';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorAlert from '../common/ErrorAlert';
import { useSmartSearch } from '../../hooks/useSmartSearch';
import { getWorkerStatus } from '../../api/dogs';
import { RiMagicFill } from 'react-icons/ri';
import { PiInfoBold } from 'react-icons/pi';
import InfoTip from '../common/InfoTip';
import './NaturalSearchPage.css';

const EXAMPLES = [
  'Shepherd, good with elderly',
  'Medium-sized pit bull',
  'Big female dog, good with cats',
  'A Rottweiler-type dog, good with people',
];

function sentenceCase(s) {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Strings carrying intentional casing (breed names, multi-word tags from
// the DB) keep their casing verbatim. Pure-lowercase enum values
// (validator-normalised: "small", "male", …) get a sentence-case bump.
function displayValue(v) {
  if (typeof v !== 'string') return String(v);
  if (/[A-Z]/.test(v)) return v;
  return sentenceCase(v);
}

function ExtractedFiltersDisplay({ filters }) {
  const entries = Object.entries(filters);

  if (entries.length === 0) {
    return (
      <div className="extracted-filters">
        <PiInfoBold className="filter-note-icon" />
        <span>No specific preferences were extracted. Showing general results.</span>
      </div>
    );
  }

  const badges = [];
  for (const [key, value] of entries) {
    const label = key.replace(/_/g, ' ');
    if (Array.isArray(value)) {
      value.forEach((v) => badges.push({ label, value: v }));
    } else {
      badges.push({ label, value });
    }
  }

  return (
    <div className="extracted-filters">
      <span className="extracted-filters-label">
        <RiMagicFill /> AI understood:
      </span>
      <div className="extracted-filters-badges">
        {badges.map((b, i) => (
          <Badge key={i} bg="light" text="dark" className="extracted-filter-badge">
            {sentenceCase(b.label)}: {displayValue(b.value)}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function NaturalSearchPage() {
  const {
    query, setQuery,
    limit, setLimit,
    results, loading, error,
    search, clearSearch,
  } = useSmartSearch();

  const [workerBusy, setWorkerBusy] = useState(false);

  useEffect(() => {
    getWorkerStatus()
      .then((data) => setWorkerBusy(data.busy))
      .catch(() => setWorkerBusy(false));
  }, []);

  const handleSearch = () => search(query, limit);

  const handleExample = (example) => {
    setQuery(example);
    search(example, limit);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSearch();
    }
  };

  const canSearch = query.trim().length > 0 && !loading && !workerBusy;

  return (
    <div>
      <div className="page-header">
        <h2>
          Smart Search
          <InfoTip id="smart-search-page-tip" placement="bottom">
            The AI extracts size, breed, age, gender, fur, weight, and compatibility from your description.
          </InfoTip>
        </h2>
      </div>

      {workerBusy && (
        <Alert variant="warning" className="mb-3">
          Data update in progress. Search functionality is temporarily disabled until the server finishes refreshing its database.
        </Alert>
      )}

      {/* Search panel */}
      <div className="smart-search-panel">
        <Form.Group className="mb-3">
          <Form.Label className="small text-muted mb-1">Describe your ideal dog</Form.Label>
          <Form.Control
            as="textarea"
            rows={3}
            placeholder="e.g., I'm looking for a medium-sized female dog, good with children, maybe a Labrador or Golden Retriever..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <div className="smart-search-hint">Press Ctrl+Enter to search</div>
        </Form.Group>

        <Row className="align-items-end g-2">
          <Col xs="auto">
            <Form.Group>
              <Form.Label className="small text-muted mb-1">Max results</Form.Label>
              <Form.Control
                type="number"
                size="sm"
                min={1}
                max={50}
                value={limit}
                onChange={(e) => setLimit(Math.max(1, Math.min(50, Number(e.target.value) || 10)))}
              />
            </Form.Group>
          </Col>
          <Col xs="auto">
            <div className="d-flex gap-2">
              <Button size="sm" variant="primary" onClick={handleSearch} disabled={!canSearch}>
                {loading ? 'Searching...' : 'Search'}
              </Button>
              <Button size="sm" variant="outline-secondary" onClick={clearSearch} disabled={loading}>
                Clear
              </Button>
            </div>
          </Col>
        </Row>
      </div>

      {/* Example queries */}
      <div className="smart-search-examples">
        <span className="smart-search-examples-label">Try:</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            className="smart-search-example-btn"
            onClick={() => handleExample(ex)}
            disabled={loading || workerBusy}
          >
            {ex}
          </button>
        ))}
      </div>

      {/* All results hidden when worker is busy to avoid API calls */}
      {!workerBusy && (
        <>
          {/* Extracted filters */}
          {results && <ExtractedFiltersDisplay filters={results.extracted_filters} />}

          {/* Error */}
          {error && <ErrorAlert message={error} />}

          {/* Loading */}
          {loading && <LoadingSpinner text="AI is analyzing your request..." />}

          {/* Results */}
          {!loading && results && (
            <>
              <p className="text-muted mb-3 mt-3">
                {results.total} {results.total === 1 ? 'dog' : 'dogs'} found
              </p>
              <DogCardGrid dogs={results.dogs} />
              {results.total === 0 && (
                <p className="smart-search-empty-hint">
                  Try broadening your description or use <Link to="/filter">Search & Filter</Link> for more control.
                </p>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

export default NaturalSearchPage;
