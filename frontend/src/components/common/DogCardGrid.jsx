import Row from 'react-bootstrap/Row';
import Col from 'react-bootstrap/Col';
import DogCard from './DogCard';

function DogCardGrid({ dogs }) {
  if (!dogs || dogs.length === 0) {
    return <p className="text-muted text-center py-4">No dogs found.</p>;
  }

  return (
    <Row xs={1} sm={2} md={3} lg={4} className="g-3">
      {dogs.map((dog) => (
        <Col key={dog.id}>
          <DogCard dog={dog} />
        </Col>
      ))}
    </Row>
  );
}

export default DogCardGrid;
