import { createProgram } from "./shader";

export type GlassFrame = {
  canvasWidth:number;canvasHeight:number;x:number;y:number;width:number;height:number;
  roiLeft:number;roiTop:number;dpr:number;
  strength:number;pinch:number;aberration:number;zoom:number;wobble:number;time:number;
};

/** Owns the GPU objects and uploaded texture; never reads DOM layout. */
export function createGlassRenderer(canvas:HTMLCanvasElement) {
  const context=canvas.getContext("webgl",{alpha:true,antialias:false,premultipliedAlpha:true,preserveDrawingBuffer:false});
  if (!context) return null;
  const gl:WebGLRenderingContext=context;
  const program=createProgram(gl);
  if (!program) return null;
  const position=gl.createBuffer(),uv=gl.createBuffer(),texture=gl.createTexture();
  if (!position||!uv||!texture) {
    if (position) gl.deleteBuffer(position);
    if (uv) gl.deleteBuffer(uv);
    if (texture) gl.deleteTexture(texture);
    gl.deleteProgram(program);return null;
  }
  gl.bindBuffer(gl.ARRAY_BUFFER,position);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
  const posLocation=gl.getAttribLocation(program,"a_position");
  gl.enableVertexAttribArray(posLocation);
  gl.vertexAttribPointer(posLocation,2,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,uv);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([0,0,1,0,0,1,0,1,1,0,1,1]),gl.STATIC_DRAW);
  const uvLocation=gl.getAttribLocation(program,"a_uv");
  gl.enableVertexAttribArray(uvLocation);
  gl.vertexAttribPointer(uvLocation,2,gl.FLOAT,false,0,0);
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D,texture);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
  const uniforms={
    texture:gl.getUniformLocation(program,"u_texture"),
    resolution:gl.getUniformLocation(program,"u_resolution"),
    lensCenter:gl.getUniformLocation(program,"u_lensCenter"),
    lensSize:gl.getUniformLocation(program,"u_lensSize"),
    strength:gl.getUniformLocation(program,"u_strength"),
    pinch:gl.getUniformLocation(program,"u_pinch"),
    aberration:gl.getUniformLocation(program,"u_aberration"),
    zoom:gl.getUniformLocation(program,"u_zoom"),
    wobble:gl.getUniformLocation(program,"u_wobble"),
    time:gl.getUniformLocation(program,"u_time"),
  };
  let textureInitialized=false;
  const maxTextureSize=gl.getParameter(gl.MAX_TEXTURE_SIZE) as number;
  function resetTexture(){textureInitialized=false;}
  function upload(image:HTMLCanvasElement){
    if(gl.isContextLost()){textureInitialized=false;return false;}
    try{
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D,texture);
      if(!textureInitialized){
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);
        textureInitialized=true;
      }else{
        gl.texSubImage2D(gl.TEXTURE_2D,0,0,0,gl.RGBA,gl.UNSIGNED_BYTE,image);
      }
      return true;
    }catch(error){
      console.warn("PowerBid liquid cursor texture upload failed:",error);
      textureInitialized=false;return false;
    }
  }
  function render(frame:GlassFrame){
    if(!textureInitialized||gl.isContextLost())return;
    gl.viewport(0,0,frame.canvasWidth,frame.canvasHeight);
    gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(program);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,texture);
    gl.uniform1i(uniforms.texture,0);
    gl.uniform2f(uniforms.resolution,frame.canvasWidth,frame.canvasHeight);
    gl.uniform2f(uniforms.lensCenter,(frame.x-frame.roiLeft)*frame.dpr,(frame.y-frame.roiTop)*frame.dpr);
    gl.uniform2f(uniforms.lensSize,frame.width*frame.dpr,frame.height*frame.dpr);
    gl.uniform1f(uniforms.strength,frame.strength);
    gl.uniform1f(uniforms.pinch,frame.pinch);
    gl.uniform1f(uniforms.aberration,frame.aberration);
    gl.uniform1f(uniforms.zoom,frame.zoom);
    gl.uniform1f(uniforms.wobble,frame.wobble);
    gl.uniform1f(uniforms.time,frame.time);
    gl.drawArrays(gl.TRIANGLES,0,6);
  }
  function dispose(){
    gl.deleteTexture(texture);gl.deleteBuffer(position);gl.deleteBuffer(uv);gl.deleteProgram(program);
  }
  return{maxTextureSize,resetTexture,upload,render,dispose};
}
