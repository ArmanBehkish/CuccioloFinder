import Form from 'react-bootstrap/Form';

function FilterDropdown({ label, value, options = [], onChange }) {
  return (
    <Form.Group>
      <Form.Label className="small text-muted mb-1">{label}</Form.Label>
      <Form.Select
        size="sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">All</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </Form.Select>
    </Form.Group>
  );
}

export default FilterDropdown;
