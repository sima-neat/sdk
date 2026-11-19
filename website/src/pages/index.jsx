import React from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import CodeBlock from '@theme/CodeBlock';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import copy from '../content/site-copy.json';
import manifest from '../../docs-manifest.json';
import ImageBuilderIcon from '../components/icons/image-builder.svg';
import SdkStackIcon from '../components/icons/sdk-stack.svg';
import ExampleImageIcon from '../components/icons/example-image.svg';

export default function Home() {
  const {i18n} = useDocusaurusContext();
  const text = copy[i18n.currentLocale] || copy.en;
  return (
    <Layout title={text.title} description={text.description}>
      <main className="sdk-home">
        <section className="sdk-intro">
          <div className="sdk-intro-copy">
            <p className="sdk-eyebrow">{text.eyebrow}</p>
            <h1>{text.title}</h1>
            <p className="sdk-lead">{text.description}</p>
            <div className="sdk-actions">
              <Link className="button button--primary" to="/guides/pib/">{text.primary}</Link>
              <Link className="sdk-text-link" to="/guides/sdk-architecture/">{text.secondary} <span aria-hidden="true">→</span></Link>
            </div>
          </div>
          <aside className="sdk-terminal">
            <p>{text.terminal}</p>
            <CodeBlock language="bash">{`sima-cli neat install ${manifest.installTarget}\npib init my-image --example custom-image`}</CodeBlock>
          </aside>
        </section>
        <section className="sdk-paths" aria-labelledby="paths-title">
          <h2 id="paths-title">{text.pathsTitle}</h2>
          <article>
            <h3><SdkStackIcon className="sdk-path-icon" aria-hidden="true" focusable="false" /><span>{text.sdkTitle}</span></h3>
            <p>{text.sdkDescription}</p>
            <Link to="/guides/sdk-architecture/">{text.sdkLink} <span aria-hidden="true">→</span></Link>
          </article>
          <article>
            <h3><ImageBuilderIcon className="sdk-path-icon" aria-hidden="true" focusable="false" /><span>{text.pibTitle}</span></h3>
            <p>{text.pibDescription}</p>
            <Link to="/guides/pib/">{text.pibLink} <span aria-hidden="true">→</span></Link>
          </article>
          <article>
            <h3><ExampleImageIcon className="sdk-path-icon" aria-hidden="true" focusable="false" /><span>{text.exampleTitle}</span></h3>
            <p>{text.exampleDescription}</p>
            <Link to="/guides/pib-example/">{text.exampleLink} <span aria-hidden="true">→</span></Link>
          </article>
        </section>
        <section className="sdk-workflow" aria-labelledby="workflow-title">
          <h2 id="workflow-title">{text.workflowTitle}</h2>
          <ol>{text.steps.map(([title, description]) => <li key={title}><h3>{title}</h3><p>{description}</p></li>)}</ol>
        </section>
        <section className="sdk-application">
          <h2>{text.applicationTitle}</h2>
          <p>{text.applicationDescription}</p>
          <a href="https://developer.sima.ai/software">{text.applicationLink} <span aria-hidden="true">↗</span></a>
        </section>
        <section className="sdk-reference">
          <p>{text.reference}</p>
          <Link to="/guides/pib-reference/">{text.referenceLink} <span aria-hidden="true">→</span></Link>
        </section>
      </main>
    </Layout>
  );
}
