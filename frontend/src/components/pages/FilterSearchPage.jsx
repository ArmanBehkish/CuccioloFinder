import { useState, useEffect, useRef } from 'react';
import Row from 'react-bootstrap/Row';
import Col from 'react-bootstrap/Col';
import Form from 'react-bootstrap/Form';
import Button from 'react-bootstrap/Button';
import Alert from 'react-bootstrap/Alert';
import { Typeahead } from 'react-bootstrap-typeahead';
import 'react-bootstrap-typeahead/css/Typeahead.css';
import FilterDropdown from '../common/FilterDropdown';
import DogCardGrid from '../common/DogCardGrid';
import Pagination from '../common/Pagination';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorAlert from '../common/ErrorAlert';
import { useEnums } from '../../hooks/useEnums';
import { useFilterSearch, TIME_INTERVALS } from '../../hooks/useFilterSearch';
import { getWorkerStatus } from '../../api/dogs';
import { PiCatFill } from 'react-icons/pi';
import InfoTip from '../common/InfoTip';
import './FilterSearchPage.css';

function FilterSearchPage() {
  const [workerBusy, setWorkerBusy] = useState(null); // null = checking, true/false = known
  const { enums, loading: enumsLoading, error: enumsError, refreshEnums } = useEnums(workerBusy === false);
  const {
    filters,
    updateFilter,
    resetFilters,
    page,
    totalPages,
    results,
    loading,
    error,
    search,
  } = useFilterSearch();

  useEffect(() => {
    getWorkerStatus()
      .then((data) => setWorkerBusy(data.busy))
      .catch(() => setWorkerBusy(false));
  }, []);

  // Load initial results on mount (skip if worker busy or restored from session)
  useEffect(() => {
    if (workerBusy !== false) return;
    if (!results) search(filters);
  }, [workerBusy]); // eslint-disable-line react-hooks/exhaustive-deps

  const breedClaimedRef = useRef();
  const breedDetectedRef = useRef();

  // Date filters only make sense for shelters whose scrapers actually
  // populate `post_date` / `shelter_since`. The API derives the supporting
  // shelters from the live data (see `_reload_caches` → `date_support`),
  // so newly-supporting spiders show up automatically after a refresh.
  // No shelter chosen → show the filter so the user can scope across the
  // shelter(s) that do expose the date.
  const postDateShelters = enums?.date_support?.post_date || [];
  const shelterSinceShelters = enums?.date_support?.shelter_since || [];
  const postedFilterEnabled = !filters.source_site
    || postDateShelters.includes(filters.source_site);
  const shelterSinceFilterEnabled = !filters.source_site
    || shelterSinceShelters.includes(filters.source_site);

  // Clear an interval value the moment its filter is disabled, so it can't
  // silently apply across a shelter switch.
  useEffect(() => {
    if (!postedFilterEnabled && filters.posted_interval) {
      updateFilter('posted_interval', '');
    }
    if (!shelterSinceFilterEnabled && filters.shelter_interval) {
      updateFilter('shelter_interval', '');
    }
  }, [postedFilterEnabled, shelterSinceFilterEnabled]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSearch = () => search(filters, 1);

  const handleReset = async () => {
    // Reset also refreshes API-side enum/stat caches before reloading results.
    await refreshEnums();
    resetFilters();
    if (breedClaimedRef.current) breedClaimedRef.current.clear();
    if (breedDetectedRef.current) breedDetectedRef.current.clear();
    search({
      source_site: '', gender: '', size: '', breed_claimed: '', breed_detected: '',
      age: '', fur: '', weight: '', good_with: '', bad_with: '',
      microchip: '', sterilization: '', vaccine: '', deworming: '',
      posted_interval: '', shelter_interval: '',
    }, 1);
  };

  const handlePageChange = (newPage) => search(filters, newPage);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSearch();
  };

  if (workerBusy === null) return <LoadingSpinner text="Checking server status..." />;
  if (!workerBusy && enumsLoading) return <LoadingSpinner text="Loading filters..." />;
  if (!workerBusy && enumsError) return <ErrorAlert message={`Failed to load filters: ${enumsError}`} />;

  return (
    <div>
      <div className="page-header">
        <h2>
          Search & Filter
          <InfoTip id="filter-page-tip" placement="bottom">
            Not all fields are available for every dog. Leave filters empty to see all dogs, or choose only the shelter to see all dogs there. Reset for a new search.
          </InfoTip>
        </h2>
      </div>

      {workerBusy && (
        <Alert variant="warning" className="mb-3">
          Data update in progress. Search functionality is temporarily disabled until the server finishes refreshing its database.
        </Alert>
      )}

      {/* Filter panel */}
      <div className="filter-panel" onKeyDown={handleKeyDown}>
        {/* Row 1 */}
        <Row className="g-2 mb-2">
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Shelter"
              value={filters.source_site}
              options={enums?.source_site || []}
              onChange={(v) => updateFilter('source_site', v)}
            />
          </Col>
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Gender"
              value={filters.gender}
              options={enums?.gender_en || []}
              onChange={(v) => updateFilter('gender', v)}
            />
          </Col>
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Size"
              value={filters.size}
              options={enums?.size_en || []}
              onChange={(v) => updateFilter('size', v)}
            />
          </Col>
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Age"
              value={filters.age}
              options={enums?.age_category || []}
              onChange={(v) => updateFilter('age', v)}
            />
          </Col>
        </Row>

        {/* Row 2 — breed pair (claimed vs AI-detected) + fur/weight */}
        <Row className="g-2 mb-2">
          <Col xs={6} md={3}>
            <Form.Group>
              <Form.Label className="small text-muted mb-1">
                Claimed Breed
                <InfoTip id="filter-breed-claimed-tip">
                  Breed explicitly announced by the shelter — either in a breed field or in the description.
                </InfoTip>
              </Form.Label>
              <Typeahead
                ref={breedClaimedRef}
                id="breed-claimed-typeahead"
                size="sm"
                options={enums?.breed_claimed || []}
                placeholder="Start typing..."
                defaultInputValue={filters.breed_claimed || ''}
                onChange={(selected) => updateFilter('breed_claimed', selected[0] || '')}
                onInputChange={(text) => updateFilter('breed_claimed', text)}
                minLength={1}
              />
            </Form.Group>
          </Col>
          <Col xs={6} md={3}>
            <Form.Group>
              <Form.Label className="small text-muted mb-1">
                Detected Breed
                <InfoTip id="filter-breed-detected-tip">
                  Breed detected by AI from the dog's photos or behaviours, when there's enough information to make a guess.
                </InfoTip>
              </Form.Label>
              <Typeahead
                ref={breedDetectedRef}
                id="breed-detected-typeahead"
                size="sm"
                options={enums?.breed_detected || []}
                placeholder="Start typing..."
                defaultInputValue={filters.breed_detected || ''}
                onChange={(selected) => updateFilter('breed_detected', selected[0] || '')}
                onInputChange={(text) => updateFilter('breed_detected', text)}
                minLength={1}
              />
            </Form.Group>
          </Col>
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Fur"
              value={filters.fur}
              options={enums?.fur_en || []}
              onChange={(v) => updateFilter('fur', v)}
            />
          </Col>
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Weight"
              value={filters.weight}
              options={enums?.weight || []}
              onChange={(v) => updateFilter('weight', v)}
            />
          </Col>
        </Row>

        {/* Row 3 */}
        <Row className="g-2 mb-2">
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Good With"
              value={filters.good_with}
              options={enums?.good_with_en || []}
              onChange={(v) => updateFilter('good_with', v)}
            />
          </Col>
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Bad With"
              value={filters.bad_with}
              options={enums?.bad_with_en || []}
              onChange={(v) => updateFilter('bad_with', v)}
            />
          </Col>
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Microchip"
              value={filters.microchip}
              options={enums?.microchip_en || []}
              onChange={(v) => updateFilter('microchip', v)}
            />
          </Col>
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Sterilization"
              value={filters.sterilization}
              options={enums?.sterilization_en || []}
              onChange={(v) => updateFilter('sterilization', v)}
            />
          </Col>
        </Row>

        {/* Row 4 */}
        <Row className="g-2 mb-2">
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Vaccine"
              value={filters.vaccine}
              options={enums?.vaccine_en || []}
              onChange={(v) => updateFilter('vaccine', v)}
            />
          </Col>
          <Col xs={6} md={3}>
            <FilterDropdown
              label="Deworming"
              value={filters.deworming}
              options={enums?.deworming_en || []}
              onChange={(v) => updateFilter('deworming', v)}
            />
          </Col>
          <Col xs={6} md={3}>
            <Form.Group>
              <Form.Label className="small text-muted mb-1">
                Posted on Site
                <InfoTip id="filter-posted-tip">
                  Only available for: {postDateShelters.length ? postDateShelters.join(', ') : 'no shelters yet'}.
                </InfoTip>
              </Form.Label>
              <Form.Select
                size="sm"
                value={filters.posted_interval}
                onChange={(e) => updateFilter('posted_interval', e.target.value)}
                disabled={!postedFilterEnabled}
                title={postedFilterEnabled ? undefined
                  : 'Not available for this shelter — pick a shelter that posts listing dates.'}
              >
                <option value="">All</option>
                {TIME_INTERVALS.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </Form.Select>
            </Form.Group>
          </Col>
          <Col xs={6} md={3}>
            <Form.Group>
              <Form.Label className="small text-muted mb-1">
                In Shelter Since
                <InfoTip id="filter-shelter-since-tip">
                  Only available for: {shelterSinceShelters.length ? shelterSinceShelters.join(', ') : 'no shelters yet'}.
                </InfoTip>
              </Form.Label>
              <Form.Select
                size="sm"
                value={filters.shelter_interval}
                onChange={(e) => updateFilter('shelter_interval', e.target.value)}
                disabled={!shelterSinceFilterEnabled}
                title={shelterSinceFilterEnabled ? undefined
                  : 'Not available for this shelter — pick a shelter that reports intake dates.'}
              >
                <option value="">All</option>
                {TIME_INTERVALS.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </Form.Select>
            </Form.Group>
          </Col>
        </Row>

        {/* Row 5 — actions */}
        <div className="filter-actions">
          <Button variant="primary" onClick={handleSearch} disabled={loading || workerBusy}>
            {loading ? 'Searching...' : 'Search'}
          </Button>
          <Button variant="outline-secondary" onClick={handleReset} disabled={loading || workerBusy}>
            Reset
          </Button>
        </div>
      </div>

      <div className="filter-note filter-note-fun">
        <PiCatFill className="filter-note-icon" />
        <span>If a cat sneaks into the listings, don't be mad — they're just desperate to be adopted too. Be nice to them :)</span>
      </div>

      {/* Results — hidden when worker is busy to avoid API calls */}
      {!workerBusy && error && <ErrorAlert message={error} onDismiss={() => search(filters, page)} />}

      {!workerBusy && loading && <LoadingSpinner text="Searching..." />}

      {!workerBusy && !loading && results && (
        <>
          <p className="text-muted mb-3 mt-4">
            {results.total} {results.total === 1 ? 'dog' : 'dogs'} found
          </p>
          <DogCardGrid dogs={results.dogs} />
          <Pagination page={page} totalPages={totalPages} onPageChange={handlePageChange} />
        </>
      )}
    </div>
  );
}

export default FilterSearchPage;
