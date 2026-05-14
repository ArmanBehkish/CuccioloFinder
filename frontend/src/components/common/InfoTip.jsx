import OverlayTrigger from 'react-bootstrap/OverlayTrigger';
import Tooltip from 'react-bootstrap/Tooltip';
import { BsInfoCircle } from 'react-icons/bs';

// Small hollow info icon that reveals a tooltip on hover/focus.
// Mirrors the design used on DogDetailPage.
function InfoTip({ id, children, placement = 'top' }) {
  return (
    <OverlayTrigger placement={placement} overlay={<Tooltip id={id}>{children}</Tooltip>}>
      <span className="info-tip" tabIndex={0}>
        <BsInfoCircle />
      </span>
    </OverlayTrigger>
  );
}

export default InfoTip;
