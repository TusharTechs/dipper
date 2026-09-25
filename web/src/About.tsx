export default function About() {
  return (
    <div className="page prose">
      <h1>How Dipper works</h1>
      <p className="lead">Citizens see sewage entering urban streams long before any sampling programme does. Dipper turns their reports into a search that finds the polluting pipe in a few checks, and hands the result to the water utility and public health in a standard format.</p>
      <ol className="steps">
        <li><h2>Reports become evidence</h2><p>A report such as "grey water, sewage smell" is placed on the stream network built from OpenStreetMap, with its flow direction and culverts.</p></li>
        <li><h2>One estimate of what and where</h2><p>Dipper keeps a probability for six explanations (sewage, overflow, chemical, sediment, algae, natural) and for every candidate outfall. Dry weather favours a misconnected pipe; rain favours an overflow.</p></li>
        <li><h2>Clean results count</h2><p>A clean look at the stream lowers the chance that the source is upstream of that point. Discharges can be intermittent, so clean never means impossible.</p></li>
        <li><h2>The next best check</h2><p>Every possible check (a quick look, an ammonium strip, a lab sample) at every place is scored by how much it would narrow the search and whether it could change the decision to warn the public, minus its effort.</p></li>
        <li><h2>People decide</h2><p>Investigators hand cases to the utility. Public-health officers approve advisories. Every decision is signed and kept in an audit trail. AI reads photos as a weaker witness and never overrides a person.</p></li>
      </ol>
      <h2>What is real and what is simulated</h2>
      <p>Stream maps, culverts, nearby places and weather are real. In the demo, candidate outfalls, reports and check results are simulated and labelled. Benchmark results (SourceBench) are simulations. Photo analysis was smoke-tested on 35 openly licensed photos.</p>
      <h2>Built on OneAquaHealth</h2>
      <p>Dipper reads the OneAquaHealth citizen-app protocol, uses the OneAquaHealth FHIR implementation guide for every hand-off, and demonstrates on Ribeira de Coselhas, a OneAquaHealth research stream in Coimbra.</p>
      <p className="muted small">Source code: <a href="https://github.com/TusharTechs/dipper">github.com/TusharTechs/dipper</a> (Apache-2.0).</p>
    </div>
  )
}
