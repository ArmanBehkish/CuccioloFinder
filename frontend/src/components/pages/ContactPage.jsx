import { useState, useRef } from 'react';
import Row from 'react-bootstrap/Row';
import Col from 'react-bootstrap/Col';
import Form from 'react-bootstrap/Form';
import Button from 'react-bootstrap/Button';
import Alert from 'react-bootstrap/Alert';
import HCaptcha from '@hcaptcha/react-hcaptcha';
import InfoTip from '../common/InfoTip';
import { LuMessageSquare, LuHeart, LuUsers, LuExternalLink, LuStar, LuCheck, LuGithub } from 'react-icons/lu';
import { PiPawPrintFill } from 'react-icons/pi';
import './ContactPage.css';

const SHELTERS = [
  { name: 'Quattro Zampe in Famiglia', url: 'https://www.quattrozampeinfamiglia.it' },
  { name: 'Albero di Mais', url: 'https://alberodimais.it' },
  { name: 'Empethy — Rifugio Impronta Creativa Torino', url: 'https://www.empethy.it/organizzazioni/rifugio-impronta-creativa-torino' },
  { name: 'ENPA Sezione Torino', url: 'https://www.voltoweb.it/enpasezionetorino/' },
  { name: 'Canile Oasi', url: 'https://canileoasi.it' },
];

const WEB3FORMS_KEY = import.meta.env.VITE_WEB3FORMS_KEY;
const HCAPTCHA_SITE_KEY = import.meta.env.VITE_HCAPTCHA_SITE_KEY;
// 'normal' (visible checkbox) or 'invisible' (auto-run, only shows challenge
// when risk model flags). Localhost forces a puzzle in invisible mode, so we
// keep dev on 'normal' and try 'invisible' only on production.
const HCAPTCHA_MODE = import.meta.env.VITE_HCAPTCHA_MODE || 'normal';
const WEB3FORMS_ENDPOINT = 'https://api.web3forms.com/submit';

function ContactPage() {
  const [form, setForm] = useState({ name: '', email: '', subject: '', message: '' });
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);
  // hCaptcha (standard checkbox) writes its token here via onVerify. Send
  // is disabled until the user has solved the captcha — required because
  // Web3Forms rejects any submission without a valid token.
  const [captchaToken, setCaptchaToken] = useState('');
  const captchaRef = useRef(null);
  const invisibleCaptcha = HCAPTCHA_MODE === 'invisible';

  const updateField = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));

  // For invisible mode the token is requested on submit, so we don't gate
  // the button on having one. For checkbox mode the user must solve first.
  // Email is optional — visitors who don't expect a reply can leave it blank.
  const baseFieldsOk = form.name.trim() && form.subject && form.message.trim();
  const canSend = baseFieldsOk && !sending && (invisibleCaptcha || captchaToken);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSend) return;
    setSending(true);
    setError(null);

    // Invisible mode: request a token now. Checkbox mode: token's already
    // in state from onVerify.
    let token = captchaToken;
    if (invisibleCaptcha) {
      try {
        const { response } = await captchaRef.current.execute({ async: true });
        token = response || '';
      } catch {
        token = '';
      }
    }

    try {
      const data = new FormData();
      data.append('access_key', WEB3FORMS_KEY);
      data.append('subject', `[CuccioloFinder] ${form.subject}`);
      data.append('from_name', form.name);
      data.append('email', form.email);
      data.append('message', form.message);
      // Web3Forms reads this and rejects non-empty submissions.
      data.append('botcheck', '');
      if (token) data.append('h-captcha-response', token);

      const res = await fetch(WEB3FORMS_ENDPOINT, { method: 'POST', body: data });
      const json = await res.json().catch(() => ({}));

      if (res.ok && json.success) {
        setSent(true);
        setForm({ name: '', email: '', subject: '', message: '' });
      } else {
        setError(json.message || 'Could not send the message. Please try again later.');
      }
    } catch {
      setError('Network error — please check your connection and try again.');
    } finally {
      setSending(false);
      // hCaptcha tokens are single-use — reset so the next submission needs a fresh solve.
      setCaptchaToken('');
      captchaRef.current?.resetCaptcha();
    }
  };

  return (
    <div className="contact-page">
      <div className="page-header">
        <h2>Contact Me</h2>
        <p>Have a question, want to help, or just want to say hello? I'd love to hear from you.</p>
      </div>

      <Row className="g-4">
        {/* Left column — Contact form */}
        <Col lg={7}>
          <div className="contact-card">
            <div className="contact-card-header">
              <LuMessageSquare className="contact-card-icon" />
              <h5>Send a Message</h5>
            </div>

            {sent ? (
              <div className="contact-success">
                <PiPawPrintFill className="contact-success-icon" />
                <p>Thank you for your message! I'll get back to you soon.</p>
                <Button size="sm" variant="outline-secondary" onClick={() => setSent(false)}>
                  Send another message
                </Button>
              </div>
            ) : (
              <Form onSubmit={handleSubmit}>
                <Row className="g-3 mb-3">
                  <Col sm={6}>
                    <Form.Group>
                      <Form.Label className="contact-label">Name</Form.Label>
                      <Form.Control
                        size="sm"
                        placeholder="Your name"
                        value={form.name}
                        onChange={(e) => updateField('name', e.target.value)}
                      />
                    </Form.Group>
                  </Col>
                  <Col sm={6}>
                    <Form.Group>
                      <Form.Label className="contact-label">
                        Email
                        <InfoTip id="contact-email-tip">
                          Leave your email if you expect a response.
                        </InfoTip>
                      </Form.Label>
                      <Form.Control
                        size="sm"
                        type="email"
                        placeholder="your@email.com"
                        value={form.email}
                        onChange={(e) => updateField('email', e.target.value)}
                      />
                    </Form.Group>
                  </Col>
                </Row>
                <Form.Group className="mb-3">
                  <Form.Label className="contact-label">Subject</Form.Label>
                  <Form.Control
                    size="sm"
                    placeholder="What is this about?"
                    value={form.subject}
                    onChange={(e) => updateField('subject', e.target.value)}
                  />
                </Form.Group>
                <Form.Group className="mb-3">
                  <Form.Label className="contact-label">Message</Form.Label>
                  <Form.Control
                    as="textarea"
                    rows={5}
                    placeholder="Tell me what's on your mind..."
                    value={form.message}
                    onChange={(e) => updateField('message', e.target.value)}
                  />
                </Form.Group>

                {/* Honeypot — humans never see this; bots tend to fill every input.
                 *   Web3Forms drops the submission server-side when `botcheck` is non-empty. */}
                <input
                  type="checkbox"
                  name="botcheck"
                  tabIndex={-1}
                  autoComplete="off"
                  style={{ display: 'none' }}
                />

                {/* hCaptcha widget. Mode is env-driven (VITE_HCAPTCHA_MODE):
                 * 'invisible' runs on submit and ideally never shows a puzzle;
                 * 'normal' is a tiny checkbox. Dev uses 'normal' because
                 * localhost forces a puzzle in invisible mode anyway. */}
                <div className="contact-captcha">
                  <HCaptcha
                    sitekey={HCAPTCHA_SITE_KEY}
                    size={invisibleCaptcha ? 'invisible' : 'normal'}
                    ref={captchaRef}
                    onVerify={(token) => setCaptchaToken(token)}
                    onExpire={() => setCaptchaToken('')}
                    onError={() => setCaptchaToken('')}
                  />
                </div>

                {error && (
                  <Alert
                    variant="danger"
                    className="contact-error d-flex align-items-center"
                    onClose={() => setError(null)}
                    dismissible
                  >
                    <span className="flex-grow-1">{error}</span>
                  </Alert>
                )}

                <Button type="submit" variant="primary" size="sm" disabled={!canSend}>
                  {sending ? 'Sending...' : 'Send Message'}
                </Button>

                <p className="contact-disclosure">
                  Protected by hCaptcha. By submitting you accept its{' '}
                  <a href="https://www.hcaptcha.com/privacy" target="_blank" rel="noopener noreferrer">Privacy Policy</a>
                  {' '}and{' '}
                  <a href="https://www.hcaptcha.com/terms" target="_blank" rel="noopener noreferrer">Terms</a>.
                </p>
              </Form>
            )}
          </div>
        </Col>

        {/* Right column — Info cards */}
        <Col lg={5}>
          {/* Support */}
          <div className="contact-card contact-card-donate">
            <div className="contact-card-header">
              <LuHeart className="contact-card-icon" />
              <h5>Support the Project</h5>
            </div>
            <p className="contact-card-text">
              CuccioloFinder is a passion project built in free time and out of love for shelter dogs. It is not intended as a business or a source of income. However, keeping a web server running with the resources needed to power the AI models / LLM APIs, along with the time spent updating and maintaining the code, does come at a cost. Small donations help keep this project going and are greatly appreciated.
            </p>
            <div className="donate-buttons">
              <a href="https://ko-fi.com/cucciolofinder" className="donate-link" target="_blank" rel="noopener noreferrer">Buy Me a Coffee</a>
            </div>
          </div>

          {/* Get Involved */}
          <div className="contact-card">
            <div className="contact-card-header">
              <LuUsers className="contact-card-icon" />
              <h5>Get Involved</h5>
            </div>
            <ul className="contact-list">
              <li><LuStar className="contact-list-icon" /> Share CuccioloFinder with friends and on social media</li>
              <li><LuStar className="contact-list-icon" /> Visit and support the partner shelters</li>
              <li><LuStar className="contact-list-icon" /> Foster or adopt a dog</li>
              <li>
                <LuStar className="contact-list-icon" />{' '}
                Suggest improvements or report issues via the form or{' '}
                <a href="https://github.com/ArmanBehkish/CuccioloFinder/issues" target="_blank" rel="noopener noreferrer">
                  GitHub issues
                </a>
              </li>
            </ul>
          </div>

          {/* Open source */}
          <div className="contact-card">
            <div className="contact-card-header">
              <LuGithub className="contact-card-icon" />
              <h5>Open Source</h5>
            </div>
            <p className="contact-card-text">
              CuccioloFinder is open source. Browse the code, file issues, or contribute on GitHub.
            </p>
            <div className="donate-buttons">
              <a
                href="https://github.com/ArmanBehkish/CuccioloFinder"
                className="github-link"
                target="_blank"
                rel="noopener noreferrer"
              >
                <LuGithub className="github-link-icon" /> View on GitHub
              </a>
            </div>
          </div>

          {/* Shelter contacts */}
          <div className="contact-card">
            <div className="contact-card-header">
              <PiPawPrintFill className="contact-card-icon" />
              <h5>Partner Shelters</h5>
            </div>
            <p className="contact-card-text">
              Interested in adopting? Contact the shelters directly:
            </p>
            <ul className="contact-shelter-list">
              {SHELTERS.map((s) => (
                <li key={s.name}>
                  <LuCheck className="contact-shelter-check" />
                  <a href={s.url} target="_blank" rel="noopener noreferrer">
                    {s.name} <LuExternalLink className="contact-external-icon" />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </Col>
      </Row>
    </div>
  );
}

export default ContactPage;
