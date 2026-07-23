import Link from 'next/link';
import { LayoutDashboard, Database, Settings, MessageSquare, Bell, BarChart2, Activity, Globe } from 'lucide-react';

const menuItems = [
  { name: 'Overview', icon: LayoutDashboard, href: '/' },
  { name: 'Opportunities', icon: Database, href: '/opportunities' },
  { name: 'Projects', icon: Globe, href: '/projects' },
  { name: 'Hermes AI', icon: MessageSquare, href: '/ai-chat' },
  { name: 'Notifications', icon: Bell, href: '/notifications' },
  { name: 'System Health', icon: Activity, href: '/health' },
  { name: 'Settings', icon: Settings, href: '/settings' },
];

export default function Sidebar() {
  return (
    <aside className="w-64 bg-gray-900 border-r border-gray-800 text-gray-300 flex flex-col h-screen fixed">
      <div className="p-6">
        <h1 className="text-2xl font-bold text-white tracking-wider flex items-center gap-2">
          <span className="bg-blue-600 p-1.5 rounded-lg text-white">
            <BarChart2 size={24} />
          </span>
          HERMES
        </h1>
      </div>
      <nav className="flex-1 px-4 space-y-2 mt-4">
        {menuItems.map((item) => (
          <Link key={item.name} href={item.href} className="flex items-center gap-3 px-4 py-3 hover:bg-gray-800 rounded-xl transition-colors">
            <item.icon size={20} />
            {item.name}
          </Link>
        ))}
      </nav>
      <div className="p-4 border-t border-gray-800">
        <div className="text-xs text-gray-500 text-center">Hermes AI Dashboard v1.0</div>
      </div>
    </aside>
  );
}
