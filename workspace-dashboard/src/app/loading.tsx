export default function Loading() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 p-8">
      <div className="w-full max-w-4xl space-y-6">
        <div className="flex justify-between items-center mb-8">
          <div className="space-y-2">
            <div className="h-8 w-48 bg-gray-800 rounded-lg animate-pulse" />
            <div className="h-4 w-64 bg-gray-900 rounded-lg animate-pulse" />
          </div>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="h-32 bg-gray-900 rounded-2xl animate-pulse" />
          ))}
        </div>

        <div className="h-96 bg-gray-900 rounded-2xl animate-pulse mt-8" />
      </div>
    </div>
  );
}
