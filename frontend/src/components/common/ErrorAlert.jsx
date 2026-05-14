import Alert from 'react-bootstrap/Alert';

function ErrorAlert({ message, onDismiss }) {
  return (
    <Alert variant="danger" dismissible={!!onDismiss} onClose={onDismiss}>
      {message}
    </Alert>
  );
}

export default ErrorAlert;
