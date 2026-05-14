import { Fragment } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Row from 'react-bootstrap/Row';
import Col from 'react-bootstrap/Col';
import Carousel from 'react-bootstrap/Carousel';
import Table from 'react-bootstrap/Table';
import Badge from 'react-bootstrap/Badge';
import Button from 'react-bootstrap/Button';
import OverlayTrigger from 'react-bootstrap/OverlayTrigger';
import Tooltip from 'react-bootstrap/Tooltip';
import { BsInfoCircle } from 'react-icons/bs';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorAlert from '../common/ErrorAlert';
import { useDogDetail } from '../../hooks/useDogDetail';
import { resolveImageUrl } from '../../config';
import './DogDetailPage.css';

function InfoTip({ id, children }) {
  return (
    <OverlayTrigger placement="top" overlay={<Tooltip id={id}>{children}</Tooltip>}>
      <span className="info-tip" tabIndex={0}>
        <BsInfoCircle />
      </span>
    </OverlayTrigger>
  );
}

function ProfileRow({ label, value, descriptionValue }) {
  const displayValue = value || descriptionValue;
  const fromDescription = !value && Boolean(descriptionValue);

  return (
    <tr>
      <td className="detail-label">{label}</td>
      <td>
        {displayValue ? (
          <span className="detail-value-with-source">
            <span>{displayValue}</span>
            {fromDescription && (
              <span
                className="detail-desc-marker"
                title="Extracted from the shelter description"
              >
                From DESC
              </span>
            )}
          </span>
        ) : (
          <span className="text-muted">Unknown</span>
        )}
      </td>
    </tr>
  );
}

const EMPTY_COMPATIBILITY_VALUES = new Set(['null', 'none', 'unknown', 'n/a', 'na']);
const EMPTY_BREED_VALUES = new Set([
  'null',
  'none',
  'unknown',
  'n/a',
  'na',
  'not detected',
  'no text data',
  'no image data',
]);

function uniqueValues(values) {
  const seen = new Set();
  const cleaned = [];

  for (const value of values || []) {
    if (typeof value !== 'string') continue;

    const trimmed = value.trim();
    const key = trimmed.toLowerCase();
    if (!trimmed || EMPTY_COMPATIBILITY_VALUES.has(key) || seen.has(key)) continue;

    seen.add(key);
    cleaned.push(trimmed);
  }

  return cleaned;
}

function descriptionOnlyValues(descriptionValues, primaryValues) {
  const primarySet = new Set(uniqueValues(primaryValues).map((value) => value.toLowerCase()));
  return uniqueValues(descriptionValues).filter((value) => !primarySet.has(value.toLowerCase()));
}

function cleanBreedValue(value) {
  if (typeof value !== 'string') return null;

  const trimmed = value.trim();
  if (!trimmed || EMPTY_BREED_VALUES.has(trimmed.toLowerCase())) return null;

  return trimmed;
}

function DogDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { dog, loading, error } = useDogDetail(id);

  if (loading) return <LoadingSpinner text="Loading dog profile..." />;
  if (error) return <ErrorAlert message={error} />;
  if (!dog) return <ErrorAlert message="Dog not found" />;

  const images = (dog.images || []).map((img) => ({
    ...img,
    resolvedUrl: resolveImageUrl(img.url),
  }));

  const goodWith = uniqueValues(dog.good_with_en);
  const badWith = uniqueValues(dog.bad_with_en);
  const goodWithFromDesc = descriptionOnlyValues(dog.good_with_from_desc, goodWith);
  const badWithFromDesc = descriptionOnlyValues(dog.bad_with_from_desc, badWith);
  const reportedBreed = cleanBreedValue(dog.breed_en);
  const reportedBreedFromDesc = cleanBreedValue(dog.breed_from_desc);
  const imageBreeds = (dog.inferred_breeds || [])
    .filter((entry) => entry.method === 'image' || entry.method === 'image_2nd')
    .map((entry) => ({ ...entry, value: cleanBreedValue(entry.value) }))
    .filter((entry) => entry.value)
    .sort((a, b) => (b.confidence ?? -1) - (a.confidence ?? -1));
  // cat_similarity coverage is dog-level, so `_2nd` carries the exact same
  // value as the primary. Render the % once, between the two ranked rows, to
  // convey that it's shared rather than per-breed.
  const catSimilarityBreeds = (dog.inferred_breeds || [])
    .filter((entry) => entry.method === 'cat_similarity' || entry.method === 'cat_similarity_2nd')
    .map((entry) => ({ ...entry, value: cleanBreedValue(entry.value) }))
    .filter((entry) => entry.value)
    .sort((a, b) => (a.method === 'cat_similarity' ? -1 : 1));

  return (
    <div className="dog-detail">
      <Button
        variant="outline-secondary"
        size="sm"
        className="mb-3"
        onClick={() => navigate(-1)}
      >
        &larr; Back
      </Button>

      <h2 className="dog-detail-name">{dog.name}</h2>
      <p className="text-muted mb-3">
        {dog.post_date && <>Posted {dog.post_date}</>}
        {dog.post_date && dog.shelter_since && <> &middot; </>}
        {dog.shelter_since && <>In shelter since {dog.shelter_since.split('T')[0]}</>}
      </p>

      <Row className="g-4 mb-4">
        {/* Image carousel */}
        <Col md={6} className="dog-detail-media-col d-flex">
          {images.length > 0 ? (
            <Carousel className="dog-detail-carousel w-100" interval={null}>
              {images.map((img, i) => (
                <Carousel.Item key={i}>
                  <a href={img.resolvedUrl} target="_blank" rel="noopener noreferrer">
                    <img
                      src={img.resolvedUrl}
                      alt={`${dog.name} photo ${i + 1}`}
                      className="d-block w-100 dog-detail-carousel-img"
                    />
                  </a>
                </Carousel.Item>
              ))}
            </Carousel>
          ) : (
            <div className="dog-detail-no-photo w-100">No photos available</div>
          )}
        </Col>

        {/* Profile table */}
        <Col md={6}>
          <div className="detail-section-box">
            <div className="detail-section-title">General Information</div>
            <Table size="sm" className="dog-detail-table">
              <tbody>
                <tr>
                  <td className="detail-label">Shelter</td>
                  <td><span className="dog-detail-source">{dog.source_site}</span></td>
                </tr>
                <ProfileRow label="Gender" value={dog.gender_en} descriptionValue={dog.gender_from_desc} />
                <ProfileRow label="Age" value={dog.age_en} descriptionValue={dog.age_from_desc} />
                <ProfileRow label="Size" value={dog.size_en} descriptionValue={dog.size_from_desc} />
                <ProfileRow label="Weight" value={dog.weight} descriptionValue={dog.weight_from_desc} />
                <ProfileRow label="Fur" value={dog.fur_en} descriptionValue={dog.fur_from_desc} />
                <ProfileRow label="Microchip" value={dog.microchip_en} descriptionValue={dog.microchip_from_desc} />
                <ProfileRow label="Sterilization" value={dog.sterilization_en} descriptionValue={dog.sterilization_from_desc} />
                <ProfileRow label="Vaccine" value={dog.vaccine_en} descriptionValue={dog.vaccine_from_desc} />
                <ProfileRow label="Deworming" value={dog.deworming_en} descriptionValue={dog.deworming_from_desc} />
              </tbody>
            </Table>
          </div>

	          <div className="detail-section-box" style={{ marginTop: '1rem' }}>
	            <div className="detail-section-title">
	              AI Breed Detection
	              <InfoTip id="ai-breed-section-tip">
	                Both methods are educated guesses, not definitive matches.
	                Shelter profiles rarely carry enough specific detail to pin
	                down an exact breed — the behaviour route especially.
	              </InfoTip>
	            </div>
	            <Table size="sm" className="dog-detail-table">
	              <tbody>
		                <ProfileRow label="Reported Breed" value={reportedBreed} descriptionValue={reportedBreedFromDesc} />
                <tr>
                  <td className="detail-label">
                    Image
                    <InfoTip id="image-method-tip">
                      Top two breed guesses from a vision model run on the
                      dog's photos.
                    </InfoTip>
                  </td>
                  <td>
                    {imageBreeds.length > 0 ? (
                      <div className="breed-method-grid">
                        {imageBreeds.map((entry, i) => (
                          <Fragment key={entry.method}>
                            <div className={`breed-guess${i > 0 ? ' breed-guess-secondary' : ''}`}>
                              <span className="breed-guess-rank">{i + 1}</span>{' '}{entry.value}
                            </div>
                            <div className="breed-method-pct-cell">
                              {entry.confidence != null && (
                                <span className="breed-confidence">
                                  {Math.round(entry.confidence * 100)}%
                                </span>
                              )}
                              {i === 0 && entry.confidence != null && (
                                <InfoTip id="image-pct-tip">
                                  How visually similar the photos look to
                                  that breed, according to the image AI.
                                </InfoTip>
                              )}
                            </div>
                          </Fragment>
                        ))}
                      </div>
                    ) : (
                      <span className="text-muted">Unknown</span>
                    )}
                  </td>
                </tr>
                <tr>
                  <td className="detail-label">
                    Described Behaviour
                    <InfoTip id="behaviour-method-tip">
                      Top two breed guesses from traits found in the
                      description.
                    </InfoTip>
                  </td>
                  <td>
                    {catSimilarityBreeds.length === 0 ? (
                      <span className="text-muted">Unknown</span>
                    ) : catSimilarityBreeds.length === 1 ? (
                      <div className="breed-method-grid">
                        <div className="breed-guess">
                          <span className="breed-guess-rank">1</span>{' '}{catSimilarityBreeds[0].value}
                        </div>
                        <div className="breed-method-pct-cell">
                          {catSimilarityBreeds[0].confidence != null && (
                            <>
                              <span className="breed-confidence">
                                {Math.round(catSimilarityBreeds[0].confidence * 100)}%
                              </span>
                              <InfoTip id="behaviour-pct-tip">
                                How much of the dog's described traits we
                                could use to compare against breed profiles.
                              </InfoTip>
                            </>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="breed-method-grid">
                        <div className="breed-guess">
                          <span className="breed-guess-rank">1</span>{' '}{catSimilarityBreeds[0].value}
                        </div>
                        <div className="breed-method-pct-cell breed-method-pct-cell-shared">
                          {catSimilarityBreeds[0].confidence != null && (
                            <>
                              <span className="breed-confidence">
                                {Math.round(catSimilarityBreeds[0].confidence * 100)}%
                              </span>
                              <InfoTip id="behaviour-pct-tip">
                                How much of the dog's described traits we
                                could use to compare against breed profiles.
                              </InfoTip>
                            </>
                          )}
                        </div>
                        <div className="breed-guess breed-guess-secondary">
                          <span className="breed-guess-rank">2</span>{' '}{catSimilarityBreeds[1].value}
                        </div>
                      </div>
                    )}
                  </td>
                </tr>
              </tbody>
            </Table>
          </div>

        </Col>
      </Row>

      {/* Compatibility */}
      {(goodWith.length > 0 || badWith.length > 0 || goodWithFromDesc.length > 0 || badWithFromDesc.length > 0) && (
        <div className="mb-4">
          <h5 className="dog-detail-section-heading">Compatibility</h5>
          <div className="d-flex flex-wrap gap-2">
            {goodWith.map((item) => (
              <Badge key={item} bg="" className="badge-good-with">{item}</Badge>
            ))}
            {goodWithFromDesc.map((item) => (
              <Badge key={`good-desc-${item}`} bg="" className="badge-good-with badge-from-desc">
                {item}
                <span className="compat-desc-marker">DESC</span>
              </Badge>
            ))}
            {badWith.map((item) => (
              <Badge key={item} bg="" className="badge-bad-with">{item}</Badge>
            ))}
            {badWithFromDesc.map((item) => (
              <Badge key={`bad-desc-${item}`} bg="" className="badge-bad-with badge-from-desc">
                {item}
                <span className="compat-desc-marker">DESC</span>
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Description */}
      {dog.description_en && (
        <div className="mb-4">
          <h5 className="dog-detail-section-heading">Description</h5>
          <div className="dog-detail-description-box">
            <p className="dog-detail-description">{dog.description_en}</p>
          </div>
        </div>
      )}

      {/* External link */}
      {dog.source_url && (
        <a
          href={dog.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-outline-secondary btn-sm"
        >
          View on shelter site &rarr;
        </a>
      )}
    </div>
  );
}

export default DogDetailPage;
