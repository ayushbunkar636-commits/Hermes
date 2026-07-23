'use client';
import { useEffect, useState } from 'react';
import { Save, AlertCircle } from 'lucide-react';

export default function SettingsPage() {
  const [settings, setSettings] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const [platformInput, setPlatformInput] = useState('');

  useEffect(() => {
    fetch('/api/settings')
      .then(res => res.json())
      .then(d => {
        setSettings(d);
        if (d.platforms) {
          setPlatformInput(d.platforms.join(', '));
        }
        setLoading(false);
      });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage('');
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      if (res.ok) {
        setMessage('Settings saved successfully to Postgres Database.');
      } else {
        setMessage('Failed to save settings.');
      }
    } catch (e) {
      setMessage('Error saving settings.');
    }
    setSaving(false);
  };

  // Removed buggy handleArrayChange

  const handleNestedChange = (field: string, subfield: string, val: string) => {
    setSettings({
      ...settings,
      [field]: { ...settings[field], [subfield]: parseInt(val) || 0 }
    });
  };

  if (loading || !settings) return <div className="text-white">Loading settings from database...</div>;

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">System Settings</h1>
        <p className="text-gray-400">Configure Hermes AI core engine directly in the Postgres database.</p>
      </div>

      {message && (
        <div className="bg-green-900/30 border border-green-800 text-green-400 px-4 py-3 rounded-lg flex items-center gap-2">
          <AlertCircle size={18} /> {message}
        </div>
      )}

      <div className="space-y-6">
        {/* Core Settings */}
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl">
          <h2 className="text-xl font-semibold text-white mb-4 border-b border-gray-800 pb-2">Core Gating</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Minimum Approval Score (0-100)</label>
              <input 
                type="number" 
                value={settings.min_score} 
                onChange={e => setSettings({...settings, min_score: parseInt(e.target.value)})}
                className="w-full bg-gray-950 border border-gray-700 text-white px-4 py-2 rounded-lg"
              />
              <p className="text-xs text-gray-500 mt-1">Cards below this score will be auto-rejected.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Schedule Frequency (Minutes)</label>
              <input 
                type="number" 
                value={settings.schedule_frequency_minutes} 
                onChange={e => setSettings({...settings, schedule_frequency_minutes: parseInt(e.target.value)})}
                className="w-full bg-gray-950 border border-gray-700 text-white px-4 py-2 rounded-lg"
              />
              <p className="text-xs text-gray-500 mt-1">How often the background orchestrator triggers hunts.</p>
            </div>
          </div>
        </div>

        {/* AI Configuration */}
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl">
          <h2 className="text-xl font-semibold text-white mb-4 border-b border-gray-800 pb-2">AI Configuration</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">AI Model</label>
              <select 
                value={settings.ai_model} 
                onChange={e => setSettings({...settings, ai_model: e.target.value})}
                className="w-full bg-gray-950 border border-gray-700 text-white px-4 py-2 rounded-lg"
              >
                <option value="vertex/gemini-2.5-flash">Qwen 3 Coder (Local)</option>
                <option value="vertex/gemini-3.1-flash-lite">Gemini 3.1 Flash Lite</option>
                <option value="vertex/gemini-3.1-pro">Gemini 3.1 Pro</option>
                <option value="openai/gpt-4o">GPT-4o</option>
              </select>
            </div>
            <div className="flex flex-col justify-center">
              <label className="flex items-center gap-3 cursor-pointer mt-4">
                <input 
                  type="checkbox" 
                  checked={settings.learning_enabled}
                  onChange={e => setSettings({...settings, learning_enabled: e.target.checked})}
                  className="w-5 h-5 bg-gray-950 border-gray-700 rounded text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm font-medium text-white">Enable Reinforcement Learning</span>
              </label>
              <p className="text-xs text-gray-500 mt-1 ml-8">AI adapts based on approval/rejection feedback.</p>
            </div>
          </div>
        </div>

        {/* Platforms */}
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl">
          <h2 className="text-xl font-semibold text-white mb-4 border-b border-gray-800 pb-2">Platform Scanning</h2>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Active Platforms (Comma separated)</label>
            <input 
              type="text" 
              value={platformInput} 
              onChange={e => {
                setPlatformInput(e.target.value);
                const arr = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
                setSettings({ ...settings, platforms: arr });
              }}
              className="w-full bg-gray-950 border border-gray-700 text-white px-4 py-2 rounded-lg"
            />
            <p className="text-xs text-gray-500 mt-1">e.g., reddit, news, linkedin, hackernews</p>
          </div>
        </div>

        {/* Reminder Intervals */}
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl">
          <h2 className="text-xl font-semibold text-white mb-4 border-b border-gray-800 pb-2">Telegram Reminder Alerts (Hours)</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Standard Reminder</label>
              <input 
                type="number" 
                value={settings.reminder_intervals_hours.standard} 
                onChange={e => handleNestedChange('reminder_intervals_hours', 'standard', e.target.value)}
                className="w-full bg-gray-950 border border-gray-700 text-white px-4 py-2 rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Strong Reminder</label>
              <input 
                type="number" 
                value={settings.reminder_intervals_hours.strong} 
                onChange={e => handleNestedChange('reminder_intervals_hours', 'strong', e.target.value)}
                className="w-full bg-gray-950 border border-gray-700 text-white px-4 py-2 rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Auto-Archive Delay</label>
              <input 
                type="number" 
                value={settings.reminder_intervals_hours.archive} 
                onChange={e => handleNestedChange('reminder_intervals_hours', 'archive', e.target.value)}
                className="w-full bg-gray-950 border border-gray-700 text-white px-4 py-2 rounded-lg"
              />
            </div>
          </div>
        </div>

        <div className="flex justify-end pt-4">
          <button 
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-xl transition-colors font-semibold"
          >
            {saving ? 'Saving...' : <><Save size={20} /> Save Configuration</>}
          </button>
        </div>
      </div>
    </div>
  );
}
