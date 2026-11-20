import React from 'react';
import { motion, useReducedMotion, useScroll, useSpring, useTransform, useMotionValue } from 'motion/react';
import { GlassForms } from './components.jsx';

export function Reveal({ children, delay = 0, className = '' }) {
  const reduced = useReducedMotion();
  return <motion.div className={className} initial={reduced ? false : { opacity: 0, y: 28 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.15 }} transition={{ duration: 0.65, delay, ease: [0.22, 1, 0.36, 1] }}>{children}</motion.div>;
}
export function HeroGlass({ heroRef }) {
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ['start start', 'end start'] });
  const y = useTransform(scrollYProgress, [0, 1], [0, 110]);
  const rotate = useTransform(scrollYProgress, [0, 1], [0, 6]);
  return <motion.div className="hero-glass-motion" style={reduced ? {} : { y, rotate }} initial={reduced ? false : { opacity: 0, scale: 0.93 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 1.35, ease: [0.22, 1, 0.36, 1] }}><GlassForms /></motion.div>;
}
export function HoverSurface({ children, className = '' }) {
  const reduced = useReducedMotion();
  const x = useMotionValue(0); const y = useMotionValue(0);
  const rotateX = useSpring(y, { stiffness: 120, damping: 22 });
  const rotateY = useSpring(x, { stiffness: 120, damping: 22 });
  return <motion.div className={className} style={reduced ? {} : { rotateX, rotateY, transformPerspective: 1200 }} onPointerMove={event => {
    if (reduced || event.pointerType !== 'mouse') return;
    const box = event.currentTarget.getBoundingClientRect();
    x.set(((event.clientX - box.left) / box.width - 0.5) * 6);
    y.set(((event.clientY - box.top) / box.height - 0.5) * -6);
  }} onPointerLeave={() => { x.set(0); y.set(0); }}>{children}</motion.div>;
}
