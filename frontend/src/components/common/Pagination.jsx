import BsPagination from 'react-bootstrap/Pagination';

function Pagination({ page, totalPages, onPageChange }) {
  if (totalPages <= 1) return null;

  const items = [];
  const maxVisible = 5;
  let start = Math.max(1, page - Math.floor(maxVisible / 2));
  let end = Math.min(totalPages, start + maxVisible - 1);
  if (end - start < maxVisible - 1) {
    start = Math.max(1, end - maxVisible + 1);
  }

  items.push(
    <BsPagination.First key="first" disabled={page === 1} onClick={() => onPageChange(1)} />,
    <BsPagination.Prev key="prev" disabled={page === 1} onClick={() => onPageChange(page - 1)} />,
  );

  if (start > 1) {
    items.push(<BsPagination.Ellipsis key="start-ellipsis" disabled />);
  }

  for (let i = start; i <= end; i++) {
    items.push(
      <BsPagination.Item key={i} active={i === page} onClick={() => onPageChange(i)}>
        {i}
      </BsPagination.Item>,
    );
  }

  if (end < totalPages) {
    items.push(<BsPagination.Ellipsis key="end-ellipsis" disabled />);
  }

  items.push(
    <BsPagination.Next key="next" disabled={page === totalPages} onClick={() => onPageChange(page + 1)} />,
    <BsPagination.Last key="last" disabled={page === totalPages} onClick={() => onPageChange(totalPages)} />,
  );

  return (
    <div className="d-flex justify-content-center mt-4">
      <BsPagination size="sm">{items}</BsPagination>
    </div>
  );
}

export default Pagination;
