#!/usr/bin/python2.7
# -*- coding: utf-8 -*-

""" 
**Project Name:**      MakeHuman

**Product Home Page:** http://www.makehuman.org/

**Code Home Page:**    https://bitbucket.org/MakeHuman/makehuman/

**Authors:**           Jonas Hauquier

**Copyright(c):**      MakeHuman Team 2001-2014

**Licensing:**         AGPL3 (http://www.makehuman.org/doc/node/the_makehuman_application.html)

    This file is part of MakeHuman (www.makehuman.org).

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

**Coding Standards:**  See http://www.makehuman.org/node/165

Abstract
--------

Data handlers for skeletal animation.
"""

import math
import numpy as np
import numpy.linalg as la
import log


INTERPOLATION = {
    'NONE'  : 0,
    'LINEAR': 1,
    'LOG':    2
}

class AnimationTrack(object):

    def __init__(self, name, poseData, nFrames, framerate):
        """
        Create a skeletal animation track with specified name from given pose
        data. An animation track usually represents one discrete animation.

        poseData    np.array((n,4,4), dtype=np.float32)
            as a list of 4x4 pose matrices
            with n = nBones*nFrames
            pose matrices should be ordered per frame - per bone
            eg: poseData = [ B0F0, B1F0, B2F0, B0F1, B1F1, B2F1]
                with each BxFy a 4x4 pose matrix for one bone in one frame
                with x the bone index, and y the frame index
            Bones should always appear in the same order and are usually
            ordered in breadth-first fashion.
        """
        self.name = name
        self.dataLen = len(poseData)
        self.nFrames = nFrames
        self.nBones = self.dataLen/nFrames

        if self.nBones*self.nFrames != self.dataLen:
            raise RuntimeError("The specified pose data does not have the proper length. Is %s, expected %s (nBones*nFrames)." % (self.dataLen, self.nBones*self.nFrames))
        if poseData.shape != (self.dataLen, 4, 4):
            raise RuntimeError("The specified pose data does not have the proper dimensions. Is %s, expected (%s, 4, 4)" % (poseData.shape, self.dataLen))

        self._data = poseData
        self.frameRate = float(framerate)      # Numer of frames per second
        self.loop = True

        self._data_baked = None
        
        # Type of interpolation between animation frames
        #   0  no interpolation
        #   1  linear
        #   2  logarithmic   # TODO!
        self.interpolationType = 0

    @property
    def data(self):
        if self.isBaked():
            return self._data_baked
        else:
            return self._data

    def isBaked(self):
        return self._data_baked is not None

    def resetBaked(self):
        self._data_baked = None

    def bake(self, skel):
        """
        Bake animation as skinning matrices for the specified skeleton.
        Results in significant performance gain when skinning.
        We do skinning with 3x4 matrixes, as suggested in http://graphics.ucsd.edu/courses/cse169_w05/2-Skeleton.htm
        Section 2.3 (We assume the 4th column contains [0 0 0 1], so no translation) --> turns out not to be the case in our algorithm!
        """
        log.debug('Updating baked animation %s', self.name)
        bones = skel.getBones()
        if len(bones) != self.nBones:
            raise RuntimeError("Error baking animation %s: number of bones in animation data differs from bone count of skeleton %s" % (self.name, skel.name))

        old_pose = skel.getPose()
        self._data_baked = np.zeros((self.dataLen, 4, 4))

        for f_idx in xrange(self.nFrames):
            skel.setPose(self._data[f_idx:f_idx+self.nBones])
            for b_idx in xrange(self.nBones):
                idx = (f_idx * self.nBones) + b_idx
                self._data_baked[idx,:,:] = bones[b_idx].matPoseVerts[:,:]

        # TODO store translation of first bone (== root bone) separately
        skel.setPose(old_pose)

    def getAtTime(self, time):
        """
        Returns the animation state at the specified time.
        When time is between two stored frames the animation values will be
        interpolated.
        """
        frameIdx, fraction = self.getFrameIndexAtTime(time)
        if fraction == 0 or self.interpolationType == 0:
            # Discrete animation
            idx = frameIdx*self.nBones
            return self.data[idx:idx+self.nBones]
        elif self.interpolationType == 1:
            # Linear interpolation
            idx1 = frameIdx*self.nBones
            idx2 = ((frameIdx+1) % self.nFrames) * self.nBones
            return self.data[idx1:idx1+self.nBones] * (1-fraction) + \
                   self.data[idx2:idx2+self.nBones] * fraction
        elif self.interpolationType == 2:
            # Logarithmic interpolation
            pass # TODO

    def getAtFramePos(self, frame):
        frame = int(frame)
        return self.data[frame*self.nBones:(frame+1)*self.nBones]

    def getFrameIndexAtTime(self, time):
        """
        Time should be in seconds (float).
        Returns     (frameIdx, fraction)
        With fraction a number between 0 and 1 (exclusive) indicating the
        fraction of progression towards the next frame. A fraction of 0 means
        position at an exact frame.
        """
        frameIdx = float(self.frameRate) * time
        fraction, frameIdx = math.modf(frameIdx)

        if self.loop:
            # Loop from beginning
            frameIdx = frameIdx % self.nFrames
        elif frameIdx >= self.nFrames:
            # Stop at last frame
            frameIdx = self.nFrames-1
            fraction = 0

        return frameIdx, fraction

    def isLooping(self):
        return self.loop

    def setLooping(self, enabled):
        self.looping = enabled

    def getPlaytime(self):
        """
        Playtime (duration) of animation in seconds.
        """
        return float(self.nFrames)/self.frameRate

    def sparsify(self, newFrameRate):
        if newFrameRate > self.frameRate:
            raise RuntimeError("Cannot sparsify animation: new framerate %s is higher than old framerate %s." % (newFrameRate, self.frameRate))

        # Number of frames to drop
        dropFrames = int(float(self.frameRate)/float(newFrameRate))
        if dropFrames <= 0:
            return
        indxs = []
        count = 0
        for frameI in range(0,self.dataLen,self.nBones):
            if count == 0:
                indxs.extend(range(frameI,frameI+self.nBones))
            count = (count + 1) % dropFrames
        data = self.data[indxs]
        self.data = data
        self.frameRate = newFrameRate
        self.dataLen = len(self.data)
        self.nFrames = self.dataLen/self.nBones

class Pose(AnimationTrack):
    """
    A pose is an animation track with only one frame, and is not affected by
    playback time.

    It's possible to convert a frame from an animation to a pose using:
        Pose(anim.name, anim.getAtTime(t))
    or
        Pose(anim.name, anim.getAtFramePos(i))
    """

    def __init__(self, name, poseData):
        super(Pose, self).__init__(name, poseData, nFrames=1, framerate=1)

    def sparsify(self, newFrameRate):
        raise NotImplementedError("sparsify() does not exist for poses")

    def getData(self):
        """
        Structured pose data
        """
        return self.getAtFramePos(0)

    def fromUnitPose(self, unitPoseData):
        # TODO
        pass

def poseFromUnitPose(name, unitPoseData):
    # TODO
    pass

def blendPoses(poses, weights):
    """
    Blend multiple poses (or pose data constructed from an animation frame).
    """
    if len(weights) < 1:
        return None

    if len(weights) == 1:
        return poses[0].getData()

    poseData = weights[0] * poses[0]
    for pIdx, pose in poses[1:]:
        w = weights[pIdx]
        poseData += w * pose

    return poseData


class VertexBoneWeights(object):
    """
    Weighted vertex to bone assignments.
    """
    def __init__(self, data, nWeights=4, vertexCount=None):
        self._data = data
        self._compiled = None
        self._vertexCount = vertexCount
        self._nWeights = nWeights

    @property
    def data(self):
        return self._data
    
    @property
    def compiled(self):
        return self._compiled

    def isCompiled(self):
        return self.compiled != None

    def compileData(self, skel, nWeights=None):
        if nWeights != None:
            self._nWeights = nWeights
        self._compiled = _compileVertexWeights(self.data, skel, vertexCount=self._vertexCount, nWeights=self._nWeights)
        self._vertexCount = len(self._compiled)

    def clearCompiled(self):
        self._compiled = None


def _compileVertexWeights(vertBoneMapping, skel, vertexCount=None, nWeights=17):
    """
    Compile vertex weights data to a more performant per-vertex format.
    """
    if vertexCount is None:
        vertexCount = 0
        for bname, mapping in vertBoneMapping.items():
            verts,weights = mapping
            vertexCount = max(max(verts), vertexCount)
        if vertexCount:
            vertexCount += 1

    if nWeights == 3:
        dtype = [('b_idx1', np.uint32), ('b_idx2', np.uint32), ('b_idx3', np.uint32), 
                 ('wght1', np.float32), ('wght2', np.float32), ('wght3', np.float32)]
    elif nWeights == 4:
        dtype = [('b_idx1', np.uint32), ('b_idx2', np.uint32), ('b_idx3', np.uint32), ('b_idx4', np.uint32),
                 ('wght1', np.float32), ('wght2', np.float32), ('wght3', np.float32), ('wght4', np.float32)]
    elif nWeights == 17:
        dtype = [('b_idx1', np.uint32), ('b_idx2', np.uint32), ('b_idx3', np.uint32), 
                 ('b_idx4', np.uint32), ('b_idx5', np.uint32), ('b_idx6', np.uint32), 
                 ('b_idx7', np.uint32), ('b_idx8', np.uint32), ('b_idx9', np.uint32), 
                 ('b_idx10', np.uint32), ('b_idx11', np.uint32), ('b_idx12', np.uint32), 
                 ('b_idx13', np.uint32), ('b_idx14', np.uint32), ('b_idx15', np.uint32), 
                 ('b_idx16', np.uint32), ('b_idx17', np.uint32), 
                 ('wght1', np.float32), ('wght2', np.float32), ('wght3', np.float32), 
                 ('wght4', np.float32), ('wght5', np.float32), ('wght6', np.float32), 
                 ('wght7', np.float32), ('wght8', np.float32), ('wght9', np.float32), 
                 ('wght10', np.float32), ('wght11', np.float32), ('wght12', np.float32), 
                 ('wght13', np.float32), ('wght14', np.float32), ('wght15', np.float32), 
                 ('wght16', np.float32), ('wght17', np.float32)]
    else:
        dtype = [('b_idx1', np.uint32), ('wght1', np.float32)]
    compiled_vertweights = np.zeros(vertexCount, dtype=dtype)

    _ws = dict()
    b_lookup = dict([(b.name,b_idx) for b_idx,b in enumerate(skel.getBones())])
    for bname, mapping in vertBoneMapping.items():
        try:
            b_idx = b_lookup[bname]
            verts,weights = mapping
            for v_idx, wght in zip(verts, weights):
                if v_idx not in _ws:
                    _ws[v_idx] = []
                # Merge double bone assignments
                d_idx = -1
                for idx in range( len(_ws[v_idx]) ):
                    _b_idx = _ws[v_idx][idx][1]
                    if _b_idx == b_idx:
                        d_idx = idx
                if d_idx != -1:
                    #log.debug("Merging double assignment (%s, %s)", (bname, v_idx))
                    _ws[v_idx][d_idx] = (_ws[v_idx][d_idx][0] + wght, b_idx)
                else:
                    _ws[v_idx].append( (wght, b_idx) )
        except KeyError as e:
            log.warning("Bone %s not found in skeleton: %s" % (bname, e))
    for v_idx in _ws:
        # Sort by weight and keep only nWeights most significant weights
        if len(_ws[v_idx]) > nWeights:
            #log.debug("Vertex %s has too many weights (%s): %s" % (v_idx, len(_ws[v_idx]), str(sorted(_ws[v_idx], reverse=True))))
            _ws[v_idx] = sorted(_ws[v_idx], reverse=True)[:nWeights]
            # Re-normalize weights
            weightvals = np.asarray( [e[0] for e in _ws[v_idx]], dtype=np.float32)
            weightvals /= np.sum(weightvals)
            for i in xrange(nWeights):
                _ws[v_idx][i] = (weightvals[i], _ws[v_idx][i][1])
        else:
            _ws[v_idx] = sorted(_ws[v_idx], reverse=True)

    for v_idx, wghts in _ws.items():
        for i, (w, bidx) in enumerate(wghts):
            compiled_vertweights[v_idx]['wght%s' % (i+1)] = w
            compiled_vertweights[v_idx]['b_idx%s' % (i+1)] = bidx

    return compiled_vertweights

class AnimatedMesh(object):
    """
    Manages skeletal animation for a mesh or multiple meshes.
    Multiple meshes can be added each with their specific bone-to-vertex mapping
    to make it possible to play back the same animation on a skeleton attached
    to multiple meshes.
    """

    def __init__(self, skel, mesh, vertexToBoneMapping):
        self.__skeleton = skel
        self.__meshes = []
        self.__vertexToBoneMaps = []
        self.__originalMeshCoords = []
        self.addBoundMesh(mesh, vertexToBoneMapping)

        self._posed = True
        self.__animations = {}
        self.__currentAnim = None
        self.__playTime = 0.0

        self.__inPlace = False  # Animate in place (ignore translation component of animation)
        self.onlyAnimateVisible = False  # Only animate visible meshes (note: enabling this can have undesired consequences!)

    def setSkeleton(self, skel):
        self.__skeleton = skel
        self.removeAnimations(update=False)
        self.resetCompiledWeights()

    def resetCompiledWeights(self):
        for vmap in self.__vertexToBoneMaps:
            vmap.clearCompiled()

    def addAnimation(self, anim):
        """
        Add an animation to this animated mesh.
        Note: poses are simply animations with only one frame.
        """
        self.__animations[anim.name] = anim

    def resetBakedAnimations(self):
        """
        Call to invalidate baked animations when they should be re-baked after
        modifying skeleton joint positions.
        """
        for anim_name in self.getAnimations():
            anim = self.getAnimation(anim_name)
            anim.resetBaked()
        log.debug('Done baking animations')

    def getAnimation(self, name):
        return self.__animations[name]

    def hasAnimation(self, name):
        return name in self.__animations.keys()

    def getAnimations(self):
        return self.__animations.keys()

    def removeAnimations(self, update=True):
        self.resetToRestPose(update)
        self.__animations = {}

    def removeAnimation(self, name):
        del self.__animations[name]
        if self.__currentAnim and self.__currentAnim.name == name:
            self.__currentAnim = None

    def setActiveAnimation(self, name):   # TODO maybe allow blending of several activated animations
        if not name:
            self.__currentAnim = None
        else:
            self.__currentAnim = self.__animations[name]

    def getActiveAnimation(self):
        if self.__currentAnim is None:
            return None
        else:
            return self.__currentAnim

    def setAnimateInPlace(self, enable):
        self.__inPlace = enable

    def getSkeleton(self):
        return self.__skeleton

    def addBoundMesh(self, mesh, vertexToBoneMapping):
        if mesh.name in self.getBoundMeshes():
            log.warning("Replacing bound mesh with same name %s" % mesh.name)
            m, _ = self.getBoundMesh(mesh.name)
            if m == mesh:
                log.warning("Attempt to add the same bound mesh %s twice" % mesh.name)
            self.removeBoundMesh(mesh.name)

        if not isinstance(vertexToBoneMapping, VertexBoneWeights):
            vertexToBoneMapping = VertexBoneWeights(vertexToBoneMapping, nWeights=4, vertexCount=mesh.getVertexCount())

        # allows multiple meshes (also to allow to animate one model consisting of multiple meshes)
        originalMeshCoords = np.zeros((mesh.getVertexCount(),4), np.float32)
        originalMeshCoords[:,:3] = mesh.coord[:,:3]
        originalMeshCoords[:,3] = 1.0
        self.__originalMeshCoords.append(originalMeshCoords)
        if self.getSkeleton():
            log.debug("Compiling vertex bone weights for %s", mesh.name)
            vertexToBoneMapping.compileData(self.getSkeleton())
        self.__vertexToBoneMaps.append(vertexToBoneMapping)
        self.__meshes.append(mesh)

    def updateVertexWeights(self, meshName, vertexToBoneMapping):
        rIdx = self._getBoundMeshIndex(meshName)
        mesh = self.__meshes[rIdx]
        if not isinstance(vertexToBoneMapping, VertexBoneWeights):
            vertexToBoneMapping = VertexBoneWeights(vertexToBoneMapping, nWeights=4, vertexCount=mesh.getVertexCount())
        if self.getSkeleton():
            vertexToBoneMapping.compileData(self.getSkeleton())
        self.__vertexToBoneMaps[rIdx] = vertexToBoneMapping

    def removeBoundMesh(self, name):
        try:
            rIdx = self._getBoundMeshIndex(name)

            # First restore rest coords of mesh, then remove it
            try:
                self._updateMeshVerts(self.__meshes[rIdx], self.__originalMeshCoords[rIdx][:,:3])
            except:
                pass    # Don't fail if the mesh was already detached/destroyed
            del self.__meshes[rIdx]
            del self.__originalMeshCoords[rIdx]
            del self.__vertexToBoneMaps[rIdx]
        except:
            pass

    def getRestCoordinates(self, name):
        rIdx = self._getBoundMeshIndex(name)
        return self.__originalMeshCoords[rIdx][:,:3]

    def containsBoundMesh(self, mesh):
        mesh2, _ = self.getBoundMesh(mesh.name)
        return mesh2 == mesh

    def getBoundMesh(self, name):
        try:
            rIdx = self._getBoundMeshIndex(name)
        except:
            return None, None

        return self.__meshes[rIdx], self.__vertexToBoneMaps[rIdx]

    def getBoundMeshes(self):
        return [mesh.name for mesh in self.__meshes]

    def _getBoundMeshIndex(self, meshName):
        for idx, mesh in enumerate(self.__meshes):
            if mesh.name == meshName:
                return idx
        raise RuntimeError("No mesh with name %s bound to this animatedmesh" % meshName)

    def update(self, timeDeltaSecs):
        self.__playTime = self.__playTime + timeDeltaSecs
        self._pose()

    def resetTime(self):
        self.__playTime = 0.0
        self._pose()

    def setToTime(self, time, update=True):
        self.__playTime = float(time)
        if update:
            self._pose()

    def setToFrame(self, frameNb, update=True):
        if not self.__currentAnim:
            return
        frameNb = int(frameNb)
        self.__playTime = float(frameNb)/self.__currentAnim.frameRate
        if update:
            self._pose()

    def setPosed(self, posed):
        """
        Set mesh posed (True) or set to rest pose (False), changes pose state.
        """
        self._posed = posed
        self.refreshPose(True)

    def isPosed(self):
        return self._posed and self.isPoseable()

    def isPoseable(self):
        return bool(self.__currentAnim and self.getSkeleton())

    @property
    def posed(self):
        return self.isPosed()

    def resetToRestPose(self, update=True):
        """
        Remove the currently set animation/pose and reset the mesh in rest pose.
        Does not affect posed state.
        """
        self.setActiveAnimation(None)
        if update:
            self.resetTime()
        else:
            self.__playTime = 0.0

    def getTime(self):
        return self.__playTime

    def getPoseState(self):
        """
        Get the pose matrices of the active animation at the current play time.
        Returned matrices are baked (they are skin matrices, relative to bone 
        rest pose in object space) if the active animation is baked, otherwise
        they are plain pose matrices in local bone space.
        """
        poseState = self.__currentAnim.getAtTime(self.__playTime)
        if self.__inPlace:
            poseState = poseState.copy()
            # Remove translation from matrix
            poseState[:,:3,3] = np.zeros((poseState.shape[0],3), dtype=np.float32)
        return poseState

    def _pose(self):
        if self.isPosed():
            if not self.getSkeleton():
                return

            if not self.__currentAnim.isBaked():
                #self.getSkeleton().setPose(poseState)  # Old slow way of skinning

                # Ensure animation is baked for fast skinning
                self.__currentAnim.bake(self.getSkeleton())

            poseState = self.getPoseState()

            # Else we pass poseVerts matrices immediately from animation track for performance improvement (cached or baked)
            for idx,mesh in enumerate(self.__meshes):
                if self.onlyAnimateVisible and not mesh.visibility:
                    continue

                if not self.__vertexToBoneMaps[idx].isCompiled():
                    log.debug("Compiling vertex bone weights for %s", mesh.name)
                    self.__vertexToBoneMaps[idx].compileData(self.getSkeleton())

                try:
                    # Old slow way of skinning
                    #posedCoords = self.getSkeleton().skinMesh(self.__originalMeshCoords[idx], self.__vertexToBoneMaps[idx].data)

                    # New fast skinnig approach
                    posedCoords = skinMesh(self.__originalMeshCoords[idx], self.__vertexToBoneMaps[idx].compiled, poseState)
                except Exception as e:
                    log.error("Error skinning mesh %s", mesh.name, exc_info=True)
                    raise e
                # TODO you could avoid an array copy by passing the mesh.coord list directly and modifying it in place
                self._updateMeshVerts(mesh, posedCoords[:,:3])
        else:
            if self.getSkeleton():
                self.getSkeleton().setToRestPose() # TODO not strictly necessary if you only want to skin the mesh
            for idx,mesh in enumerate(self.__meshes):
                self._updateMeshVerts(mesh, self.__originalMeshCoords[idx])

    def _updateMeshVerts(self, mesh, verts):
        # TODO this is way too slow for realtime animation, but good for posing. For animation, update the r_ verts directly, as well as the r_vnorm members
        # TODO use this mapping to directly update the opengl data for animation
        # Remap vertex weights to the unwelded vertices of the object (mesh.coord to mesh.r_coord)
        #originalToUnweldedMap = mesh.inverse_vmap

        mesh.changeCoords(verts[:,:3])
        mesh.calcNormals()  # TODO this is too slow for animation
        mesh.update()

    def refreshStaticMeshes(self, refresh_pose=True):
        """
        Invoke this method after the static (rest pose) meshes were changed.
        Updates the shadow copies with original vertex coordinates and re-applies
        the pose if this animated object was in posed mode.
        """
        for mIdx, mesh in enumerate(self.__meshes):
            self.__originalMeshCoords[mIdx][:,:3] = mesh.coord[:,:3]
        if refresh_pose:
            self.refreshPose(updateIfInRest=False)

    def _updateOriginalMeshCoords(self, name, coord):
        rIdx = self._getBoundMeshIndex(name)
        self.__originalMeshCoords[rIdx][:,:3] = coord[:,:3]

    def refreshPose(self, updateIfInRest=False):
        if not self.getSkeleton():
            self.resetToRestPose()
        if updateIfInRest or self.isPosed():
            self._pose()

def skinMesh(coords, compiledVertWeights, poseData):
    """
    More efficient way of linear blend skinning or smooth skinning.
    As proposed in http://graphics.ucsd.edu/courses/cse169_w05/3-Skin.htm we use
    a vertex-major loop.
    We also use a fixed number of weights per vertex.
    Uses accumulated matrix skinning (http://http.developer.nvidia.com/GPUGems/gpugems_ch04.html)

    Care should be taken to supply coords with the right dimensions. This method
    accepts both coords[nverts, 3] and coords[nverts, 4] dimensions. The fourth
    member being the homogenous coordinate, which should be 1 if translations
    should affect the vertex position (eg for mesh coordinates), and 0 for
    rotations only (for directions such as normals, tangents and targets).
    If coords is nx3 size, this method will perform faster as only 3x3 matrix
    multiplies are performed, otherwise 3x4 matrices are multiplied.
    """
    if coords.shape[1] == 4:
        # Vertices contain homogenous coordinate (1 if translation affects position,
        # 0 if vertex should not be affected by translation (only direction) )
        c = 4
    else:
        # Translations do not affect vertices (faster as this requires only 3x3 matrix multiplies)
        c = 3

    W = compiledVertWeights
    P = poseData
    if len(compiledVertWeights.dtype) == 4*2:
        # nWeights = 4
        accum = W['wght1'][:,None,None] * P[W['b_idx1']][:,:3,:c] + \
                W['wght2'][:,None,None] * P[W['b_idx2']][:,:3,:c] + \
                W['wght3'][:,None,None] * P[W['b_idx3']][:,:3,:c] + \
                W['wght4'][:,None,None] * P[W['b_idx4']][:,:3,:c]
    elif len(compiledVertWeights.dtype) == 2:
        # nWeights = 1
        accum = W['wght1'][:,None,None] * P[W['b_idx1']][:,:3,:c]
    elif len(compiledVertWeights.dtype) == 17*2:
        # nWeights = 17
        accum = W['wght1'][:,None,None] * P[W['b_idx1']][:,:3,:c] + \
                W['wght2'][:,None,None] * P[W['b_idx2']][:,:3,:c] + \
                W['wght3'][:,None,None] * P[W['b_idx3']][:,:3,:c] + \
                W['wght4'][:,None,None] * P[W['b_idx4']][:,:3,:c] + \
                W['wght5'][:,None,None] * P[W['b_idx5']][:,:3,:c] + \
                W['wght6'][:,None,None] * P[W['b_idx6']][:,:3,:c] + \
                W['wght7'][:,None,None] * P[W['b_idx7']][:,:3,:c] + \
                W['wght8'][:,None,None] * P[W['b_idx8']][:,:3,:c] + \
                W['wght9'][:,None,None] * P[W['b_idx9']][:,:3,:c] + \
                W['wght10'][:,None,None] * P[W['b_idx10']][:,:3,:c] + \
                W['wght11'][:,None,None] * P[W['b_idx11']][:,:3,:c] + \
                W['wght12'][:,None,None] * P[W['b_idx12']][:,:3,:c] + \
                W['wght13'][:,None,None] * P[W['b_idx13']][:,:3,:c] + \
                W['wght14'][:,None,None] * P[W['b_idx14']][:,:3,:c] + \
                W['wght15'][:,None,None] * P[W['b_idx15']][:,:3,:c] + \
                W['wght16'][:,None,None] * P[W['b_idx16']][:,:3,:c] + \
                W['wght17'][:,None,None] * P[W['b_idx17']][:,:3,:c]
    else:
        # nWeights = 3
        accum = W['wght1'][:,None,None] * P[W['b_idx1']][:,:3,:c] + \
                W['wght2'][:,None,None] * P[W['b_idx2']][:,:3,:c] + \
                W['wght3'][:,None,None] * P[W['b_idx3']][:,:3,:c]

    # Note: np.sum(M * vs, axis=-1) is a matrix multiplication of mat M with
    # a series of vertices vs
    # Good resource: http://jameshensman.wordpress.com/2010/06/14/multiple-matrix-multiplication-in-numpy
    #return np.sum(accum[:,:3,:4] * coords[:,None,:], axis=-1)

    # Using einstein summation for matrix * vertex multiply, appears to be
    # slightly faster
    return np.einsum('ijk,ikl -> ij', accum[:,:3,:c], coords[:,:c,None])


def emptyTrack(nFrames, nBones=1):
    """
    Create an empty (rest pose) animation track pose data array.
    """
    nMats = nFrames*nBones
    return np.tile(np.identity(4), nMats).transpose().reshape((nMats,4,4))

def emptyPose(nBones=1):
    """
    Create an empty animation containing one frame. 
    """
    return emptyTrack(1, nBones)

def loadPoseFromMhpFile(filepath, skel):
    """
    Load a MHP pose file that contains a static pose. Posing data is defined
    with quaternions to indicate rotation angles.
    Creates a single frame animation track (a pose).
    """
    import log
    import os
    from codecs import open

    log.message("Loading MHP file %s", filepath)
    fp = open(filepath, "rU", encoding="utf-8")
    valid_file = False

    boneMap = skel.getBoneToIdxMapping()
    nBones = len(boneMap.keys())
    poseMats = np.zeros((nBones,4,4),dtype=np.float32)
    poseMats[:] = np.identity(4, dtype=np.float32)

    mats = dict()
    for line in fp:
        words = line.split()
        if len(words) > 0 and words[0].startswith('#'):
            # comment
            continue
        if len(words) < 10:
            log.warning("Too short line in mhp file: %s" % " ".join(words))
            continue
        elif words[1] == "matrix":
            bname = words[0]
            boneIdx = boneMap[bname]
            rows = []
            n = 2
            for i in range(4):
                rows.append([float(words[n]), float(words[n+1]), float(words[n+2]), float(words[n+3])])
                n += 4
            # Invert Z rotation (for some reason this is required to make MHP orientations work)
            rows[0][1] = -rows[0][1]
            rows[1][0] = -rows[1][0]
            # Invert X rotation
            #rows[1][2] = -rows[1][2]
            #rows[2][1] = -rows[2][1]
            # Invert Y rotation
            rows[0][2] = -rows[0][2]
            rows[2][0] = -rows[2][0]

            mats[boneIdx] = np.array(rows)
        else:
            log.warning("Unknown keyword in mhp file: %s" % words[1])

    if not valid_file:
        log.error("Loading of MHP file %s failed, probably a bad file." % filepath)

    '''
    # Apply pose to bones in breadth-first order (parent to child bone)
    for boneIdx in sorted(mats.keys()):
        bone = skel.boneslist[boneIdx]
        mat = mats[boneIdx]
        if bone.parent:
            mat = np.dot(poseMats[bone.parent.index], np.dot(bone.matRestRelative, mat))
        else:
            mat = np.dot(self.matRestGlobal, mat)
        poseMats[boneIdx] = mat

    for boneIdx in sorted(mats.keys()):
        bone = skel.boneslist[boneIdx]
        poseMats[boneIdx] = np.dot(poseMats[boneIdx], la.inv(bone.matRestGlobal))
    '''
    for boneIdx in sorted(mats.keys()):
        poseMats[boneIdx] = mats[boneIdx]

    fp.close()

    name = os.path.splitext(os.path.basename(filepath))[0]
    result = Pose(name, poseMats)

    return result
