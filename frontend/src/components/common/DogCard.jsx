import { useState } from 'react';
import { Link } from 'react-router-dom';
import Card from 'react-bootstrap/Card';
import Badge from 'react-bootstrap/Badge';
import { PiDogFill } from 'react-icons/pi';
import { resolveImageUrl } from '../../config';
import './DogCard.css';

const MAX_BADGES = 7;
const EMPTY_BADGE_VALUES = new Set([
  'null',
  'none',
  'unknown',
  'n/a',
  'na',
  'not detected',
]);

function cleanBadgeValue(value) {
  if (typeof value !== 'string') return null;

  const trimmed = value.trim();
  if (!trimmed || EMPTY_BADGE_VALUES.has(trimmed.toLowerCase())) return null;

  return trimmed;
}

function valueWithFallback(primaryValue, descriptionValue, formatter = (value) => value) {
  const value = cleanBadgeValue(primaryValue) || cleanBadgeValue(descriptionValue);
  return value ? formatter(value) : null;
}

function DogCard({ dog }) {
  const thumbUrl = resolveImageUrl(dog.thumbnail);
  const [imgError, setImgError] = useState(false);

  const allBadges = [
    valueWithFallback(dog.breed_en, dog.breed_from_desc),
    valueWithFallback(dog.gender_en, dog.gender_from_desc),
    valueWithFallback(dog.age_en, dog.age_from_desc),
    valueWithFallback(dog.size_en, dog.size_from_desc),
    valueWithFallback(dog.fur_en, dog.fur_from_desc, (value) => `${value} fur`),
    valueWithFallback(dog.weight, dog.weight_from_desc),
  ].filter(Boolean).slice(0, MAX_BADGES);

  const showPlaceholder = !thumbUrl || imgError;

  return (
    <Link to={`/dogs/${dog.id}`} className="dog-card-link">
      <Card className="dog-card h-100">
        {showPlaceholder ? (
          <div className="dog-card-placeholder"><PiDogFill className="dog-card-placeholder-icon" /></div>
        ) : (
          <Card.Img
            variant="top"
            src={thumbUrl}
            alt={dog.name}
            className="dog-card-img"
            onError={() => setImgError(true)}
          />
        )}
        <Card.Body className="d-flex flex-column">
          <div className="dog-card-header">
            <Card.Title className="dog-card-name">{dog.name || 'Unknown'}</Card.Title>
            <span className="dog-card-source">{dog.source_site}</span>
          </div>
          <div className="dog-card-badges">
            {allBadges.map((val) => (
              <Badge key={val} bg="light" text="dark">{val}</Badge>
            ))}
          </div>
        </Card.Body>
      </Card>
    </Link>
  );
}

export default DogCard;
