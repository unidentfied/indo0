import React, { useState } from 'react';
import { api } from '../services/api';

interface SignupModalProps {
  onClose: () => void;
}

const SignupModal: React.FC<SignupModalProps> = ({ onClose }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.auth.signup(email, password);
      setSuccess(true);
    } catch (err: any) {
      setError(err?.message ?? 'Signup failed');
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    if (!loading) {
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-sindio-panel rounded-xl shadow-xl w-full max-w-md mx-4 p-6 relative">
        <button
          type="button"
          className="absolute top-3 right-3 text-sindio-muted hover:text-sindio-accent"
          onClick={handleClose}
          disabled={loading}
        >
          ✕
        </button>
        {success ? (
          <div className="text-center">
            <h2 className="text-xl font-semibold mb-4 text-sindio-accent">
              Check your email!
            </h2>
            <p className="text-sindio-muted mb-6">
              A verification link has been sent to <strong>{email}</strong>. Please verify your account before signing in.
            </p>
            <button
              type="button"
              className="btn-primary w-full"
              onClick={handleClose}
            >
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <h2 className="text-2xl font-bold mb-4 text-sindio-accent">
              Sign up for Sindio
            </h2>
            {error && (
              <div className="bg-red-100 text-red-800 p-2 rounded mb-4 text-sm">
                {error}
              </div>
            )}
            <div className="mb-4">
              <label htmlFor="email" className="block text-sm font-medium text-sindio-muted mb-1">
                Email address
              </label>
              <input
                id="email"
                type="email"
                required
                className="w-full px-3 py-2 border border-sindio-border rounded bg-sindio-dark text-sindio-muted focus:outline-none focus:border-sindio-accent transition"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={loading}
              />
            </div>
            <div className="mb-4">
              <label htmlFor="password" className="block text-sm font-medium text-sindio-muted mb-1">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                minLength={8}
                className="w-full px-3 py-2 border border-sindio-border rounded bg-sindio-dark text-sindio-muted focus:outline-none focus:border-sindio-accent transition"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
              />
            </div>
            <button
              type="submit"
              className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
              disabled={loading}
            >
              {loading ? 'Signing up…' : 'Create Account'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};

export default SignupModal;
