import Spinner from 'react-bootstrap/Spinner';

function LoadingSpinner({ text = 'Loading...' }) {
  return (
    <div className="text-center py-5">
      <Spinner animation="border" role="status" style={{ color: 'var(--accent)' }} />
      <p className="mt-2 text-muted">{text}</p>
    </div>
  );
}

export default LoadingSpinner;
