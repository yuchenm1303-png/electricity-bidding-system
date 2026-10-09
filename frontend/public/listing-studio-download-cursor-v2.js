(() => {
  const dot = document.getElementById("cursorDot");
  const follow = document.getElementById("cursorFollow");
  if (!dot || !follow) return;

  const style = document.createElement("style");
  style.id = "reference-homepage-cursor";
  style.textContent = `
    .cursor-dot {
      position: fixed !important;
      left: 0 !important;
      top: 0 !important;
      width: 10px !important;
      height: 10px !important;
      margin: -5px 0 0 -5px !important;
      border: 0 !important;
      border-radius: 50% !important;
      background: #fff !important;
      box-shadow: none !important;
      opacity: 0 !important;
      transform: none !important;
      pointer-events: none !important;
      z-index: 10087 !important;
    }

    .cursor-dot.cursor-visible { opacity: 1 !important; }

    .cursor-follow {
      position: fixed !important;
      left: 0 !important;
      top: 0 !important;
      width: 18px !important;
      height: 18px !important;
      margin: 0 !important;
      border: 0 !important;
      border-radius: 25px !important;
      background: #fff !important;
      box-shadow: none !important;
      opacity: .25 !important;
      transform: scale(1) !important;
      pointer-events: none !important;
      z-index: 10086 !important;
      transition: .2s ease-in-out !important;
      transition-property: background, opacity, transform !important;
    }

    .cursor-follow.hidden { opacity: 0 !important; }
    .cursor-follow.active {
      opacity: .5 !important;
      transform: scale(.5) !important;
    }

    @media (max-width: 720px), (pointer: coarse) {
      .cursor-dot,
      .cursor-follow { display: none !important; }
    }
  `;
  document.head.appendChild(style);

  dot.classList.remove("cursor-visible");
  follow.classList.remove("cursor-visible", "pressed", "active");
  follow.classList.add("hidden");

  let curr = null;
  let prev = null;
  let raf = 0;

  const moveDot = (x, y) => {
    dot.style.translate = `${x}px ${y}px`;
  };

  const moveFollow = (x, y) => {
    follow.style.translate = `${x}px ${y}px`;
  };

  const render = () => {
    raf = 0;
    if (!curr) return;

    if (prev) {
      prev.x += (curr.x - prev.x) * 0.35;
      prev.y += (curr.y - prev.y) * 0.35;
      moveFollow(prev.x, prev.y);
    } else {
      prev = { ...curr };
      moveFollow(prev.x, prev.y);
    }

    if (Math.abs(curr.x - prev.x) > 0.01 || Math.abs(curr.y - prev.y) > 0.01) {
      raf = requestAnimationFrame(render);
    }
  };

  const queueRender = () => {
    if (!raf) raf = requestAnimationFrame(render);
  };

  document.addEventListener("mousemove", (event) => {
    moveDot(event.clientX, event.clientY);
    dot.classList.add("cursor-visible");

    if (curr === null) moveFollow(event.clientX - 8, event.clientY - 8);
    curr = { x: event.clientX - 8, y: event.clientY - 8 };
    follow.classList.remove("hidden");
    follow.classList.add("cursor-visible");
    queueRender();
  }, { passive: true });

  document.addEventListener("mouseenter", () => {
    dot.classList.add("cursor-visible");
    follow.classList.remove("hidden");
  });

  document.addEventListener("mouseleave", () => {
    dot.classList.remove("cursor-visible");
    follow.classList.add("hidden");
  });

  document.addEventListener("mousedown", () => follow.classList.add("active"));
  document.addEventListener("mouseup", () => follow.classList.remove("active"));

  window.addEventListener("pagehide", () => {
    if (raf) cancelAnimationFrame(raf);
  }, { once: true });
})();

(() => {
  const ANIME_SRC = "https://cdn.jsdelivr.net/npm/animejs@3.2.1/lib/anime.min.js";

  const loadAnime321 = () => {
    if (window.anime?.version === "3.2.1") return Promise.resolve(window.anime);

    return new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-listing-studio-anime="3.2.1"]');
      if (existing) {
        existing.addEventListener("load", () => resolve(window.anime), { once: true });
        existing.addEventListener("error", reject, { once: true });
        return;
      }

      const script = document.createElement("script");
      script.src = ANIME_SRC;
      script.async = true;
      script.dataset.listingStudioAnime = "3.2.1";
      script.addEventListener("load", () => resolve(window.anime), { once: true });
      script.addEventListener("error", reject, { once: true });
      document.head.appendChild(script);
    });
  };

  const setupOriginalFireworks = (anime) => {
    if (!anime) return;

    const style = document.createElement("style");
    style.id = "original-click-fireworks-style";
    style.textContent = `
      .fireworks {
        position: fixed;
        left: 0;
        top: 0;
        z-index: 999;
        pointer-events: none;
      }
    `;
    document.head.appendChild(style);

    const canvas = document.createElement("canvas");
    canvas.className = "fireworks";
    canvas.setAttribute("aria-hidden", "true");
    document.body.appendChild(canvas);

    let mouseX = 0;
    let mouseY = 0;
    let onMouseDown;
    let onResize;

    const darkColors = ["252, 146, 174", "202, 180, 190", "207, 198, 255"];
    const config = {
      colors: darkColors,
      numberOfParticles: 20,
      orbitRadius: {
        min: 50,
        max: 100
      },
      circleRadius: {
        min: 10,
        max: 20
      },
      diffuseRadius: {
        min: 50,
        max: 100
      },
      animeDuration: {
        min: 900,
        max: 1500
      }
    };

    const colors = config.colors;
    const context = canvas.getContext("2d");
    if (!context) {
      canvas.remove();
      style.remove();
      return;
    }

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
    }

    function randomEndPosition(origin) {
      const angle = anime.random(0, 360) * Math.PI / 180;
      const diffuseRadius = anime.random(config.diffuseRadius.min, config.diffuseRadius.max);
      const signedRadius = [-1, 1][anime.random(0, 1)] * diffuseRadius;
      return {
        x: origin.x + signedRadius * Math.cos(angle),
        y: origin.y + signedRadius * Math.sin(angle)
      };
    }

    function createParticle(x, y) {
      return {
        x,
        y,
        color: `rgba(${colors[anime.random(0, colors.length - 1)]},${anime.random(.2, .8)})`,
        radius: anime.random(config.circleRadius.min, config.circleRadius.max),
        angle: anime.random(0, 360),
        endPos: randomEndPosition({ x, y }),
        draw() {
          context.save();
          context.translate(this.x, this.y);
          context.rotate(this.angle * Math.PI / 180);
          context.beginPath();
          context.moveTo(0, -this.radius);
          context.lineTo(this.radius * Math.sin(Math.PI / 3), this.radius * Math.cos(Math.PI / 3));
          context.lineTo(-this.radius * Math.sin(Math.PI / 3), this.radius * Math.cos(Math.PI / 3));
          context.closePath();
          context.fillStyle = this.color;
          context.fill();
          context.restore();
        }
      };
    }

    function createCircle(x, y) {
      return {
        x,
        y,
        color: "rgb(233, 179, 237)",
        radius: .1,
        alpha: .5,
        lineWidth: 6,
        draw() {
          context.globalAlpha = this.alpha;
          context.beginPath();
          context.arc(this.x, this.y, this.radius, 0, 2 * Math.PI, true);
          context.lineWidth = this.lineWidth;
          context.strokeStyle = this.color;
          context.stroke();
          context.globalAlpha = 1;
        }
      };
    }

    function drawTargets(animation) {
      animation.animatables.forEach(({ target }) => target.draw?.());
    }

    function createFirework(x, y) {
      const circle = createCircle(x, y);
      const particles = Array.from(
        { length: config.numberOfParticles },
        () => createParticle(x, y)
      );

      anime.timeline().add({
        targets: particles,
        x: (particle) => particle.endPos.x,
        y: (particle) => particle.endPos.y,
        radius: 0,
        duration: anime.random(config.animeDuration.min, config.animeDuration.max),
        easing: "easeOutExpo",
        update: drawTargets
      }).add({
        targets: circle,
        radius: anime.random(config.orbitRadius.min, config.orbitRadius.max),
        lineWidth: 0,
        alpha: {
          value: 0,
          easing: "linear",
          duration: anime.random(600, 800)
        },
        duration: anime.random(1200, 1800),
        easing: "easeOutExpo",
        update: drawTargets
      }, 0);
    }

    const clearAnimation = anime({
      duration: Number.POSITIVE_INFINITY,
      update: () => context.clearRect(0, 0, canvas.width, canvas.height)
    });

    onResize = () => resize();
    onMouseDown = (event) => {
      clearAnimation.play();
      mouseX = event.clientX;
      mouseY = event.clientY;
      createFirework(mouseX, mouseY);
    };

    document.addEventListener("mousedown", onMouseDown);
    window.addEventListener("resize", onResize);
    resize();

    window.addEventListener("pagehide", () => {
      document.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("resize", onResize);
      clearAnimation.pause();
    }, { once: true });
  };

  loadAnime321().then(setupOriginalFireworks).catch(() => {});
})();
