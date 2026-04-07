const plans = [
  {
    name: 'Free',
    price: '$0',
    credits: '50 credits/month',
    features: ['Quick analyses (< 10 files)', 'GitHub integration', 'Basic findings'],
    cta: 'Get started free',
    href: '/signup',
    highlight: false,
  },
  {
    name: 'Starter',
    price: '$49/mo',
    credits: '300 credits/month',
    features: ['Full analyses (up to 50 files)', 'All SCM providers', 'Code suggestions', 'Overage at $0.35/credit'],
    cta: 'Start Starter',
    href: '/signup',
    highlight: false,
  },
  {
    name: 'Growth',
    price: '$149/mo',
    credits: '1,000 credits/month',
    features: ['Everything in Starter', 'Scheduled analyses', 'Datadog integration', 'Team access (up to 10)', 'Overage at $0.25/credit'],
    cta: 'Start Growth',
    href: '/signup',
    highlight: true,
  },
  {
    name: 'Scale',
    price: '$449/mo',
    credits: '5,000 credits/month',
    features: ['Everything in Growth', 'Unlimited team members', 'Priority support', 'SLA 99.9%', 'Overage at $0.15/credit'],
    cta: 'Start Scale',
    href: '/signup',
    highlight: false,
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    credits: 'Custom credits',
    features: ['Custom limits', 'Dedicated support', 'SSO/SAML', 'Custom compliance rules', 'On-prem option'],
    cta: 'Contact sales',
    href: 'mailto:sales@horion.pro',
    highlight: false,
  },
]

export default function PricingPage() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 py-16 px-4">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-gray-900 dark:text-gray-100 mb-3">Simple, usage-based pricing</h1>
          <p className="text-lg text-gray-500 dark:text-gray-400">Pay for what you analyze. No surprises.</p>
        </div>

        <div className="grid grid-cols-5 gap-4">
          {plans.map((plan) => (
            <div
              key={plan.name}
              className={`bg-white dark:bg-gray-900 rounded-xl p-6 border-2 flex flex-col ${
                plan.highlight
                  ? 'border-gray-900 dark:border-gray-100'
                  : 'border-gray-200 dark:border-gray-700'
              }`}
            >
              {plan.highlight && (
                <div className="text-xs font-bold text-gray-900 dark:text-gray-100 uppercase mb-2">Most popular</div>
              )}
              <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">{plan.name}</h2>
              <div className="text-2xl font-bold text-gray-900 dark:text-gray-100 my-2">{plan.price}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400 mb-4">{plan.credits}</div>
              <ul className="space-y-2 flex-1 mb-6">
                {plan.features.map((f) => (
                  <li key={f} className="text-xs text-gray-600 dark:text-gray-400 flex items-start gap-1.5">
                    <span className="text-green-500 dark:text-green-400 mt-0.5">&#10003;</span>
                    {f}
                  </li>
                ))}
              </ul>
              <a
                href={plan.href}
                className={`block text-center py-2 rounded-lg text-sm font-medium ${
                  plan.highlight
                    ? 'bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 hover:bg-gray-700 dark:hover:bg-gray-300'
                    : 'border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
              >
                {plan.cta}
              </a>
            </div>
          ))}
        </div>

        <div className="mt-12 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-8">
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">FAQ</h2>
          <div className="grid grid-cols-2 gap-6 text-sm text-gray-600 dark:text-gray-400">
            <div>
              <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-1">What counts as an analysis?</h3>
              <p>One analysis = one PR/commit scan or one manual run. Cost depends on file count: quick (&lt;10 files) = 1 credit, full (10-50 files) = 3 credits, repository scan = 15 credits.</p>
            </div>
            <div>
              <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-1">What happens when I run out of credits?</h3>
              <p>Free plan: analyses are blocked until the next month. Paid plans: overages are billed at your plan rate. You&apos;ll see a warning in the dashboard when you&apos;re at 80%.</p>
            </div>
            <div>
              <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-1">Can I cancel anytime?</h3>
              <p>Yes. Cancel through the billing portal — you keep access until the end of your billing period. No refunds for partial months.</p>
            </div>
            <div>
              <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-1">Is there a free trial?</h3>
              <p>Yes — the Free plan gives you 50 credits every month with no credit card required. Upgrade anytime.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
